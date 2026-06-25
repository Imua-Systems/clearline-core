"""
Bitbucket adapter for Clearline ontology v1.

Transforms raw Bitbucket REST API issue dicts (with issue changes) into canonical WorkItems.
This is the only module that references Bitbucket-specific concepts.
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

BITBUCKET_STATE_MAP: dict[str, CanonicalState] = {
    "new": CanonicalState.IN_PROGRESS,
    "open": CanonicalState.IN_PROGRESS,
    "resolved": CanonicalState.DONE,
    "closed": CanonicalState.DONE,
    "on hold": CanonicalState.IN_PROGRESS,
    "invalid": CanonicalState.DONE,
    "duplicate": CanonicalState.DONE,
    "wontfix": CanonicalState.DONE,
}

TERMINAL_STATES = frozenset({"resolved", "closed", "invalid", "duplicate", "wontfix"})

UNMAPPED_STATUSES: set[str] = set()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalize_state(state: str | None) -> str | None:
    if state is None:
        return None
    return state.lower()


def _map_state(state: str | None) -> CanonicalState:
    normalized = _normalize_state(state)
    if normalized and normalized in BITBUCKET_STATE_MAP:
        return BITBUCKET_STATE_MAP[normalized]
    if normalized:
        UNMAPPED_STATUSES.add(normalized)
    return CanonicalState.BACKLOG


def _sorted_changes(changes: list[dict] | None) -> list[dict]:
    if not changes:
        return []
    return sorted(changes, key=lambda change: change.get("created_on") or "")


def _build_labels(issue: dict) -> list[str]:
    labels: list[str] = []

    component = issue.get("component")
    if component and component.get("name"):
        labels.append(component["name"])

    priority = issue.get("priority")
    if priority is not None:
        labels.append(str(priority))

    return labels


def _count_status_changes(changes: list[dict] | None) -> int:
    if changes is None:
        return 0
    return sum(
        1
        for change in changes
        if (change.get("changes") or {}).get("status") is not None
    )


def _extract_state_history(
    changes: list[dict] | None,
) -> tuple[list[StateTransition], bool]:
    if not changes:
        return [], False

    transitions: list[StateTransition] = []

    for change in _sorted_changes(changes):
        try:
            status_change = (change.get("changes") or {}).get("status")
            if not status_change:
                continue

            old_raw = _normalize_state(status_change.get("old"))
            new_raw = _normalize_state(status_change.get("new"))
            created_on = change.get("created_on")
            if not new_raw or not created_on:
                logger.warning(
                    "Skipping issue change %s: missing status or created_on",
                    change.get("id", "?"),
                )
                continue

            if old_raw and old_raw not in BITBUCKET_STATE_MAP:
                UNMAPPED_STATUSES.add(old_raw)
            if new_raw not in BITBUCKET_STATE_MAP:
                UNMAPPED_STATUSES.add(new_raw)

            user = change.get("user") or {}
            transitions.append(
                StateTransition(
                    from_state=BITBUCKET_STATE_MAP.get(old_raw) if old_raw else None,
                    to_state=BITBUCKET_STATE_MAP.get(new_raw, CanonicalState.BACKLOG),
                    transitioned_at=_parse_datetime(created_on),
                    transitioned_by=user.get("display_name"),
                    source_status=new_raw,
                )
            )
        except Exception as exc:
            logger.warning(
                "Skipping issue change %s during state history extraction: %s",
                change.get("id", "?"),
                exc,
            )
            continue

    return transitions, len(transitions) > 0


def _derive_completed_at(changes: list[dict] | None) -> datetime | None:
    completed_at: datetime | None = None

    for change in _sorted_changes(changes):
        try:
            status_change = (change.get("changes") or {}).get("status")
            if not status_change:
                continue

            new_raw = _normalize_state(status_change.get("new"))
            if new_raw not in TERMINAL_STATES:
                continue

            created_on = change.get("created_on")
            if created_on:
                completed_at = _parse_datetime(created_on)
        except Exception as exc:
            logger.warning(
                "Skipping issue change %s during completed_at derivation: %s",
                change.get("id", "?"),
                exc,
            )
            continue

    return completed_at


def bitbucket_issue_to_work_item(
    issue: dict, changes: list[dict] | None = None
) -> WorkItem:
    state_history, has_state_changes = _extract_state_history(changes)
    touch_count = _count_status_changes(changes) if changes is not None else None

    state_name = issue.get("state")
    state = _map_state(state_name)

    if changes is None:
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

    created_at = _parse_datetime(issue["created_on"])
    started_at = created_at
    completed_at = _derive_completed_at(changes)

    milestone = issue.get("milestone")
    sprint_id = milestone.get("name") if milestone else None

    assignee_obj = issue.get("assignee")
    assignee = assignee_obj.get("display_name") if assignee_obj else None

    labels = _build_labels(issue)
    item_type = issue.get("kind") or "issue"

    links = issue.get("links") or {}
    html_link = links.get("html") or {}
    source_url = html_link.get("href")

    field_confidence: dict[str, ConfidenceLevel] = {
        "state": ConfidenceLevel.EXPLICIT,
        "state_history": state_history_confidence,
        "touch_count": (
            ConfidenceLevel.INFERRED if changes is not None else ConfidenceLevel.MISSING
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
    if labels:
        field_confidence["labels"] = ConfidenceLevel.INFERRED

    return WorkItem(
        id=str(issue["id"]),
        source_system="bitbucket",
        source_url=source_url,
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
        age_in_state_days=age_in_state_days,
        touch_count=touch_count,
        field_confidence=field_confidence,
    )


BITBUCKET_MINIMAL_SAMPLE = {
    "id": 25,
    "title": "Pagination breaks when filter is applied on user list",
    "state": "new",
    "kind": "bug",
    "created_on": "2026-05-29T09:33:55.141Z",
    "links": {
        "html": {
            "href": "https://bitbucket.org/meridian/engineering/issues/25"
        }
    },
}

BITBUCKET_FULL_SAMPLE = {
    "id": 25,
    "title": "Pagination breaks when filter is applied on user list",
    "state": "resolved",
    "kind": "bug",
    "priority": "major",
    "created_on": "2026-05-29T09:33:55.141Z",
    "links": {
        "html": {
            "href": "https://bitbucket.org/meridian/engineering/issues/25"
        }
    },
    "assignee": {"display_name": "Jim Martin"},
    "milestone": {"name": "Sprint 2"},
    "component": {"name": "frontend"},
}

BITBUCKET_FULL_SAMPLE_CHANGES = [
    {
        "id": 1,
        "created_on": "2026-05-29T09:44:06.739Z",
        "user": {"display_name": "Jim Martin"},
        "changes": {
            "status": {
                "old": "open",
                "new": "resolved",
            }
        },
    },
]


if __name__ == "__main__":
    work_item = bitbucket_issue_to_work_item(
        BITBUCKET_FULL_SAMPLE, BITBUCKET_FULL_SAMPLE_CHANGES
    )
    print(json.dumps(work_item.model_dump(mode="json"), indent=2))
