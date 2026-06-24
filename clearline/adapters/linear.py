"""
Linear adapter for Clearline ontology v1.

Transforms raw Linear GraphQL API issue responses into canonical WorkItems.
This is the only module that references Linear-specific concepts.
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

LINEAR_STATE_MAP: dict[str, CanonicalState] = {
    "Backlog": CanonicalState.BACKLOG,
    "Unstarted": CanonicalState.BACKLOG,
    "Todo": CanonicalState.READY,
    "In Progress": CanonicalState.IN_PROGRESS,
    "In Review": CanonicalState.REVIEW,
    "Done": CanonicalState.DONE,
    "Cancelled": CanonicalState.ABANDONED,
    "Duplicate": CanonicalState.ABANDONED,
}

LINEAR_PRIORITY_MAP: dict[int, str | None] = {
    0: None,
    1: "Urgent",
    2: "High",
    3: "Medium",
    4: "Low",
}

UNMAPPED_STATUSES: set[str] = set()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _map_state(state: str | None) -> CanonicalState:
    if state and state in LINEAR_STATE_MAP:
        return LINEAR_STATE_MAP[state]
    if state:
        UNMAPPED_STATUSES.add(state)
    return CanonicalState.BACKLOG


def _map_priority(priority: int | None) -> str | None:
    if priority is None:
        return None
    return LINEAR_PRIORITY_MAP.get(priority)


def _infer_item_type(labels: list[str]) -> str:
    lowered = {label.lower() for label in labels}
    if "bug" in lowered:
        return "Bug"
    if "feature" in lowered:
        return "Feature"
    return "Issue"


def _history_nodes(issue: dict) -> list[dict]:
    return issue.get("history", {}).get("nodes", []) or []


def _extract_state_history(
    nodes: list[dict],
) -> tuple[list[StateTransition], bool]:
    if not nodes:
        return [], False

    transitions: list[StateTransition] = []
    has_state_changes = False

    sorted_nodes = sorted(nodes, key=lambda node: node.get("createdAt") or "")

    for node in sorted_nodes:
        try:
            to_state_obj = node.get("toState")
            if not to_state_obj:
                continue

            to_state_name = to_state_obj.get("name")
            if not to_state_name:
                continue

            from_state_obj = node.get("fromState") or {}
            from_state_name = from_state_obj.get("name")

            if from_state_name and from_state_name not in LINEAR_STATE_MAP:
                UNMAPPED_STATUSES.add(from_state_name)
            if to_state_name not in LINEAR_STATE_MAP:
                UNMAPPED_STATUSES.add(to_state_name)

            from_state = (
                LINEAR_STATE_MAP.get(from_state_name) if from_state_name else None
            )
            to_state = LINEAR_STATE_MAP.get(to_state_name, CanonicalState.BACKLOG)

            if from_state_name != to_state_name:
                has_state_changes = True

            created_at = node.get("createdAt")
            if not created_at:
                logger.warning(
                    "Skipping history node during state history extraction: no createdAt"
                )
                continue

            actor = node.get("actor") or {}
            transitioned_by = actor.get("name")

            transitions.append(
                StateTransition(
                    from_state=from_state,
                    to_state=to_state,
                    transitioned_at=_parse_datetime(created_at),
                    transitioned_by=transitioned_by,
                    source_status=to_state_name,
                )
            )
        except Exception as exc:
            logger.warning(
                "Skipping history node during state history extraction: %s",
                exc,
            )
            continue

    return transitions, has_state_changes


def _derive_started_at(nodes: list[dict]) -> datetime | None:
    sorted_nodes = sorted(nodes, key=lambda node: node.get("createdAt") or "")

    for node in sorted_nodes:
        try:
            to_state_obj = node.get("toState")
            if not to_state_obj:
                continue

            to_state_name = to_state_obj.get("name")
            if to_state_name and LINEAR_STATE_MAP.get(to_state_name) == CanonicalState.IN_PROGRESS:
                created_at = node.get("createdAt")
                if created_at:
                    return _parse_datetime(created_at)
        except Exception as exc:
            logger.warning(
                "Skipping history node during started_at derivation: %s",
                exc,
            )
            continue

    return None


def linear_issue_to_work_item(issue: dict) -> WorkItem:
    history_nodes = _history_nodes(issue)
    state_history, has_state_changes = _extract_state_history(history_nodes)
    touch_count = len(history_nodes)

    state_name = issue["state"]["name"]
    state = _map_state(state_name)
    state_confidence = (
        ConfidenceLevel.EXPLICIT
        if state_name in LINEAR_STATE_MAP
        else ConfidenceLevel.INFERRED
    )

    if not issue.get("history"):
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

    started_at = _derive_started_at(history_nodes)

    labels = [
        label["name"]
        for label in issue.get("labels", {}).get("nodes", [])
        if label.get("name")
    ]

    item_type_obj = issue.get("type") or {}
    item_type = item_type_obj.get("name") or _infer_item_type(labels)

    assignee_obj = issue.get("assignee") or {}
    assignee = assignee_obj.get("name")

    priority_value = issue.get("priority")
    priority = _map_priority(priority_value)

    parent_obj = issue.get("parent") or {}
    parent_id = parent_obj.get("identifier")

    cycle_obj = issue.get("cycle") or {}
    cycle_number = cycle_obj.get("number")
    sprint_id = str(cycle_number) if cycle_number is not None else None

    field_confidence: dict[str, ConfidenceLevel] = {
        "state": state_confidence,
        "state_history": state_history_confidence,
        "touch_count": ConfidenceLevel.INFERRED,
        "age_in_state_days": ConfidenceLevel.INFERRED,
        "started_at": (
            ConfidenceLevel.INFERRED if started_at else ConfidenceLevel.MISSING
        ),
        "assignee": ConfidenceLevel.EXPLICIT if assignee else ConfidenceLevel.MISSING,
        "priority": (
            ConfidenceLevel.EXPLICIT
            if priority_value is not None and priority_value != 0
            else ConfidenceLevel.MISSING
        ),
        "parent_id": ConfidenceLevel.EXPLICIT if parent_id else ConfidenceLevel.MISSING,
        "sprint_id": (
            ConfidenceLevel.EXPLICIT if cycle_number is not None else ConfidenceLevel.MISSING
        ),
    }

    return WorkItem(
        id=issue["identifier"],
        source_system="linear",
        source_url=issue.get("url"),
        item_type=item_type,
        title=issue["title"],
        labels=labels,
        state=state,
        state_changed_at=state_changed_at,
        state_history=state_history,
        priority=priority,
        assignee=assignee,
        created_at=_parse_datetime(issue["createdAt"]),
        started_at=started_at,
        parent_id=parent_id,
        sprint_id=sprint_id,
        age_in_state_days=age_in_state_days,
        touch_count=touch_count,
        field_confidence=field_confidence,
    )


LINEAR_SAMPLE = {
    "identifier": "ENG-123",
    "url": "https://linear.app/meridian/issue/ENG-123",
    "title": "Pagination breaks when filter is applied on user list",
    "createdAt": "2026-05-29T09:33:55.141Z",
    "state": {"name": "Done"},
    "type": {"name": "Bug"},
    "priority": 3,
    "assignee": {"name": "Jim Martin"},
    "labels": {
        "nodes": [
            {"name": "bug-reduction"},
            {"name": "frontend"},
        ]
    },
    "parent": {"identifier": "ENG-8"},
    "cycle": {"number": 2},
    "history": {
        "nodes": [
            {
                "createdAt": "2026-05-29T09:33:55.141Z",
                "fromState": None,
                "toState": {"name": "Backlog"},
                "actor": {"name": "Jim Martin"},
            },
            {
                "createdAt": "2026-05-29T09:34:53.238Z",
                "fromState": {"name": "Backlog"},
                "toState": {"name": "In Progress"},
                "actor": {"name": "Jim Martin"},
            },
            {
                "createdAt": "2026-05-29T09:44:06.739Z",
                "fromState": {"name": "In Progress"},
                "toState": {"name": "Done"},
                "actor": {"name": "Jim Martin"},
            },
        ]
    },
}


if __name__ == "__main__":
    work_item = linear_issue_to_work_item(LINEAR_SAMPLE)
    print(json.dumps(work_item.model_dump(mode="json"), indent=2))
