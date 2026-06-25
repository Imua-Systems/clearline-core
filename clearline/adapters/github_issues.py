"""
GitHub Issues adapter for Clearline ontology v1.

Transforms raw GitHub REST API issue dicts (with issue timeline events) into canonical WorkItems.
This is the only module that references GitHub Issues-specific concepts.
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

GITHUB_STATE_MAP: dict[str, CanonicalState] = {
    "open": CanonicalState.IN_PROGRESS,
    "closed": CanonicalState.DONE,
}

STATE_EVENT_TYPES = frozenset({"closed", "reopened"})

UNMAPPED_STATUSES: set[str] = set()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _map_state(state: str | None) -> CanonicalState:
    if state and state in GITHUB_STATE_MAP:
        return GITHUB_STATE_MAP[state]
    if state:
        UNMAPPED_STATUSES.add(state)
    return CanonicalState.BACKLOG


def is_github_issue(issue: dict) -> bool:
    """Return False for pull requests returned by the issues endpoint."""
    return "pull_request" not in issue


def _sorted_events(events: list[dict] | None) -> list[dict]:
    if not events:
        return []
    return sorted(events, key=lambda event: event.get("created_at") or "")


def _extract_label_names(issue: dict) -> list[str]:
    labels = issue.get("labels") or []
    names: list[str] = []
    for label in labels:
        if isinstance(label, dict):
            name = label.get("name")
            if name:
                names.append(name)
        elif isinstance(label, str):
            names.append(label)
    return names


def _count_state_events(events: list[dict] | None) -> int:
    if events is None:
        return 0
    return sum(1 for event in events if event.get("event") in STATE_EVENT_TYPES)


def _extract_state_history(
    events: list[dict] | None,
) -> tuple[list[StateTransition], bool]:
    if not events:
        return [], False

    transitions: list[StateTransition] = []
    current_state = "open"

    for event in _sorted_events(events):
        try:
            event_type = event.get("event")
            if event_type not in STATE_EVENT_TYPES:
                continue

            created_at = event.get("created_at")
            if not created_at:
                logger.warning(
                    "Skipping issue event %s: no created_at",
                    event.get("id", "?"),
                )
                continue

            if event_type == "closed":
                to_raw = "closed"
            else:
                to_raw = "open"

            from_state = GITHUB_STATE_MAP.get(current_state)
            to_state = GITHUB_STATE_MAP.get(to_raw, CanonicalState.BACKLOG)

            actor = event.get("actor") or {}
            transitioned_by = actor.get("login")

            transitions.append(
                StateTransition(
                    from_state=from_state,
                    to_state=to_state,
                    transitioned_at=_parse_datetime(created_at),
                    transitioned_by=transitioned_by,
                    source_status=to_raw,
                )
            )
            current_state = to_raw
        except Exception as exc:
            logger.warning(
                "Skipping issue event %s during state history extraction: %s",
                event.get("id", "?"),
                exc,
            )
            continue

    return transitions, len(transitions) > 0


def _derive_completed_at(events: list[dict] | None) -> datetime | None:
    completed_at: datetime | None = None

    for event in _sorted_events(events):
        try:
            if event.get("event") == "closed":
                event_created_at = event.get("created_at")
                if event_created_at:
                    completed_at = _parse_datetime(event_created_at)
        except Exception as exc:
            logger.warning(
                "Skipping issue event %s during completed_at derivation: %s",
                event.get("id", "?"),
                exc,
            )
            continue

    return completed_at


def github_issue_to_work_item(
    issue: dict, events: list[dict] | None = None
) -> WorkItem:
    state_history, has_state_changes = _extract_state_history(events)
    touch_count = _count_state_events(events) if events is not None else None

    state_name = issue.get("state")
    state = _map_state(state_name)

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
    started_at = created_at
    completed_at = _derive_completed_at(events)

    milestone = issue.get("milestone")
    sprint_id = milestone.get("title") if milestone else None

    assignee_obj = issue.get("assignee")
    assignee = assignee_obj.get("login") if assignee_obj else None

    labels = _extract_label_names(issue)

    field_confidence: dict[str, ConfidenceLevel] = {
        "state": ConfidenceLevel.EXPLICIT,
        "state_history": state_history_confidence,
        "touch_count": (
            ConfidenceLevel.INFERRED if events is not None else ConfidenceLevel.MISSING
        ),
        "age_in_state_days": ConfidenceLevel.INFERRED,
        "started_at": ConfidenceLevel.INFERRED,
    }
    if completed_at is not None:
        field_confidence["completed_at"] = ConfidenceLevel.INFERRED
    if assignee is not None:
        field_confidence["assignee"] = ConfidenceLevel.EXPLICIT
    if sprint_id is not None:
        field_confidence["sprint_id"] = ConfidenceLevel.INFERRED

    return WorkItem(
        id=str(issue["number"]),
        source_system="github_issues",
        source_url=issue.get("html_url"),
        item_type="issue",
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
        age_in_state_days=age_in_state_days,
        touch_count=touch_count,
        field_confidence=field_confidence,
    )


GITHUB_MINIMAL_SAMPLE = {
    "number": 25,
    "title": "Pagination breaks when filter is applied on user list",
    "state": "open",
    "labels": [],
    "created_at": "2026-05-29T09:33:55Z",
    "html_url": "https://github.com/meridian/engineering/issues/25",
}

GITHUB_FULL_SAMPLE = {
    "number": 25,
    "title": "Pagination breaks when filter is applied on user list",
    "state": "closed",
    "labels": [
        {"name": "bug-reduction"},
        {"name": "frontend"},
    ],
    "created_at": "2026-05-29T09:33:55Z",
    "html_url": "https://github.com/meridian/engineering/issues/25",
    "assignee": {"login": "jim-martin"},
    "milestone": {"title": "Sprint 2"},
}

GITHUB_FULL_SAMPLE_EVENTS = [
    {
        "id": 1,
        "event": "closed",
        "created_at": "2026-05-29T09:44:06Z",
        "actor": {"login": "jim-martin"},
    },
]


if __name__ == "__main__":
    work_item = github_issue_to_work_item(GITHUB_FULL_SAMPLE, GITHUB_FULL_SAMPLE_EVENTS)
    print(json.dumps(work_item.model_dump(mode="json"), indent=2))
