"""
GitLab adapter for Clearline ontology v1.

Transforms raw GitLab API issue dicts (with resource state events) into canonical WorkItems.
This is the only module that references GitLab-specific concepts.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from clearline.ontology.v1.core import (
    CanonicalState,
    ConfidenceLevel,
    StateTransition,
    WorkItem,
)

logger = logging.getLogger(__name__)

GITLAB_STATE_MAP: dict[str, CanonicalState] = {
    "opened": CanonicalState.IN_PROGRESS,
    "closed": CanonicalState.DONE,
    "locked": CanonicalState.IN_PROGRESS,
}

UNMAPPED_STATUSES: set[str] = set()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _map_state(state: str | None) -> CanonicalState:
    if state and state in GITLAB_STATE_MAP:
        return GITLAB_STATE_MAP[state]
    if state:
        UNMAPPED_STATUSES.add(state)
    return CanonicalState.BACKLOG


def _sorted_events(events: list[dict] | None) -> list[dict]:
    if not events:
        return []
    return sorted(events, key=lambda event: event.get("created_at") or "")


def _extract_state_history(
    events: list[dict] | None,
) -> tuple[list[StateTransition], bool]:
    if not events:
        return [], False

    transitions: list[StateTransition] = []
    has_state_changes = False
    prev_state: str | None = None

    for event in _sorted_events(events):
        try:
            raw_state = event.get("state")
            if not raw_state:
                continue

            if raw_state not in GITLAB_STATE_MAP:
                UNMAPPED_STATUSES.add(raw_state)

            created_at = event.get("created_at")
            if not created_at:
                logger.warning(
                    "Skipping state event %s: no created_at",
                    event.get("id", "?"),
                )
                continue

            if prev_state is not None and raw_state != prev_state:
                has_state_changes = True

                user = event.get("user") or {}
                transitioned_by = user.get("username") or user.get("name")

                transitions.append(
                    StateTransition(
                        from_state=GITLAB_STATE_MAP.get(prev_state),
                        to_state=GITLAB_STATE_MAP.get(raw_state, CanonicalState.BACKLOG),
                        transitioned_at=_parse_datetime(created_at),
                        transitioned_by=transitioned_by,
                        source_status=raw_state,
                    )
                )

            prev_state = raw_state
        except Exception as exc:
            logger.warning(
                "Skipping state event %s during state history extraction: %s",
                event.get("id", "?"),
                exc,
            )
            continue

    return transitions, has_state_changes


def _derive_started_at(
    events: list[dict] | None, created_at: datetime
) -> datetime | None:
    for event in _sorted_events(events):
        try:
            if event.get("state") == "opened":
                event_created_at = event.get("created_at")
                if event_created_at:
                    return _parse_datetime(event_created_at)
        except Exception as exc:
            logger.warning(
                "Skipping state event %s during started_at derivation: %s",
                event.get("id", "?"),
                exc,
            )
            continue

    return created_at


def _derive_completed_at(events: list[dict] | None) -> datetime | None:
    completed_at: datetime | None = None

    for event in _sorted_events(events):
        try:
            if event.get("state") == "closed":
                event_created_at = event.get("created_at")
                if event_created_at:
                    completed_at = _parse_datetime(event_created_at)
        except Exception as exc:
            logger.warning(
                "Skipping state event %s during completed_at derivation: %s",
                event.get("id", "?"),
                exc,
            )
            continue

    return completed_at


def gitlab_issue_to_work_item(issue: dict, events: list[dict] | None = None) -> WorkItem:
    state_history, has_state_changes = _extract_state_history(events)
    touch_count = len(events) if events else None

    state_name = issue.get("state")
    state = _map_state(state_name)
    state_confidence = (
        ConfidenceLevel.EXPLICIT
        if state_name in GITLAB_STATE_MAP
        else ConfidenceLevel.INFERRED
    )

    if events is None:
        state_history_confidence = ConfidenceLevel.MISSING
    elif has_state_changes:
        state_history_confidence = ConfidenceLevel.EXPLICIT
    else:
        state_history_confidence = ConfidenceLevel.INFERRED

    state_changed_at: datetime | None = None
    if state_history:
        state_changed_at = max(t.transitioned_at for t in state_history)

    now = (
        datetime.now(tz=state_changed_at.tzinfo)
        if state_changed_at and state_changed_at.tzinfo
        else datetime.now()
    )
    age_in_state_days = (now - state_changed_at).days if state_changed_at else None

    created_at = _parse_datetime(issue["created_at"])
    started_at = _derive_started_at(events, created_at) if events else None
    completed_at = _derive_completed_at(events)

    milestone = issue.get("milestone") or {}
    sprint_id = milestone.get("title")

    assignee_obj = issue.get("assignee")
    assignee = assignee_obj.get("username") if assignee_obj else None

    labels = issue.get("labels", [])
    blocking_issues = issue.get("blocking_issues") or []
    is_blocked = True if blocking_issues else None

    item_type = issue.get("issue_type") or "issue"

    field_confidence: dict[str, ConfidenceLevel] = {
        "state": state_confidence,
        "state_history": state_history_confidence,
        "touch_count": (
            ConfidenceLevel.INFERRED if touch_count is not None else ConfidenceLevel.MISSING
        ),
        "age_in_state_days": ConfidenceLevel.INFERRED,
        "started_at": (
            ConfidenceLevel.INFERRED if started_at else ConfidenceLevel.MISSING
        ),
        "completed_at": (
            ConfidenceLevel.INFERRED if completed_at else ConfidenceLevel.MISSING
        ),
        "assignee": ConfidenceLevel.EXPLICIT if assignee else ConfidenceLevel.MISSING,
        "sprint_id": ConfidenceLevel.INFERRED if sprint_id else ConfidenceLevel.MISSING,
        "is_blocked": ConfidenceLevel.INFERRED,
    }

    return WorkItem(
        id=str(issue["iid"]),
        source_system="gitlab",
        source_url=issue.get("web_url"),
        item_type=item_type,
        title=issue.get("title"),
        labels=labels,
        state=state,
        state_changed_at=state_changed_at,
        state_history=state_history,
        assignee=assignee,
        created_at=created_at,
        started_at=started_at,
        completed_at=completed_at,
        sprint_id=sprint_id,
        is_blocked=is_blocked,
        age_in_state_days=age_in_state_days,
        touch_count=touch_count,
        field_confidence=field_confidence,
    )


GITLAB_MINIMAL_SAMPLE = {
    "iid": 25,
    "title": "Pagination breaks when filter is applied on user list",
    "state": "opened",
    "labels": ["bug-reduction"],
    "created_at": "2026-05-29T09:33:55.141Z",
    "web_url": "https://gitlab.com/meridian/engineering/-/issues/25",
    "issue_type": "issue",
}

GITLAB_FULL_SAMPLE = {
    "iid": 25,
    "title": "Pagination breaks when filter is applied on user list",
    "state": "closed",
    "labels": ["bug-reduction", "frontend"],
    "created_at": "2026-05-29T09:33:55.141Z",
    "web_url": "https://gitlab.com/meridian/engineering/-/issues/25",
    "issue_type": "issue",
    "assignee": {"username": "jim.martin"},
    "milestone": {"title": "Sprint 2"},
    "blocking_issues": [{"iid": 8}],
}

GITLAB_FULL_SAMPLE_EVENTS = [
    {
        "id": 1,
        "state": "opened",
        "created_at": "2026-05-29T09:33:55.141Z",
        "user": {"username": "jim.martin"},
    },
    {
        "id": 2,
        "state": "closed",
        "created_at": "2026-05-29T09:44:06.739Z",
        "user": {"username": "jim.martin"},
    },
]


if __name__ == "__main__":
    work_item = gitlab_issue_to_work_item(GITLAB_FULL_SAMPLE, GITLAB_FULL_SAMPLE_EVENTS)
    print(json.dumps(work_item.model_dump(mode="json"), indent=2))
