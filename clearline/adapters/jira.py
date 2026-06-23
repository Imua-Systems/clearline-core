"""
Jira adapter for Clearline ontology v1.

Transforms raw Jira API issue dicts (with changelog expanded) into canonical WorkItems.
This is the only module that references Jira-specific concepts.
"""

from __future__ import annotations

import json
from datetime import datetime

from clearline.ontology.v1.core import (
    CanonicalState,
    ConfidenceLevel,
    StateTransition,
    WorkItem,
)

JIRA_STATUS_MAP: dict[str, CanonicalState] = {
    "To Do": CanonicalState.BACKLOG,
    "Backlog": CanonicalState.BACKLOG,
    "Ready": CanonicalState.READY,
    "In Progress": CanonicalState.IN_PROGRESS,
    "In Review": CanonicalState.REVIEW,
    "Review": CanonicalState.REVIEW,
    "Blocked": CanonicalState.BLOCKED,
    "Waiting": CanonicalState.WAITING,
    "Done": CanonicalState.DONE,
    "Closed": CanonicalState.DONE,
    "Won't Do": CanonicalState.ABANDONED,
    "Cancelled": CanonicalState.ABANDONED,
}

UNMAPPED_STATUSES: set[str] = set()
UNSUPPORTED_CHANGELOG_FIELDS: set[str] = set()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _map_status(status: str | None) -> CanonicalState:
    if status and status in JIRA_STATUS_MAP:
        return JIRA_STATUS_MAP[status]
    if status:
        UNMAPPED_STATUSES.add(status)
    return CanonicalState.BACKLOG


def _extract_sprint_id(fields: dict) -> str | None:
    sprints = fields.get("customfield_10020")
    if not sprints:
        return None
    if isinstance(sprints, list) and sprints:
        last = sprints[-1]
        if isinstance(last, dict):
            return last.get("name")
        return str(last)
    return None


def _extract_state_history(changelog: dict | None) -> list[StateTransition]:
    if not changelog:
        return []

    transitions: list[StateTransition] = []

    for history in changelog.get("histories", []):
        has_status = any(item.get("field") == "status" for item in history.get("items", []))
        if not has_status:
            continue

        transitioned_at = _parse_datetime(history["created"])
        transitioned_by = history.get("author", {}).get("displayName")

        for item in history.get("items", []):
            if item.get("field") != "status":
                continue

            from_string = item.get("fromString")
            to_string = item.get("toString")

            if from_string and from_string not in JIRA_STATUS_MAP:
                UNMAPPED_STATUSES.add(from_string)
            if to_string and to_string not in JIRA_STATUS_MAP:
                UNMAPPED_STATUSES.add(to_string)

            from_state = None
            if from_string:
                from_state = JIRA_STATUS_MAP.get(from_string)

            to_state = JIRA_STATUS_MAP.get(to_string, CanonicalState.BACKLOG) if to_string else CanonicalState.BACKLOG

            transitions.append(
                StateTransition(
                    from_state=from_state,
                    to_state=to_state,
                    transitioned_at=transitioned_at,
                    transitioned_by=transitioned_by,
                    source_status=to_string,
                )
            )

    transitions.sort(key=lambda t: t.transitioned_at)
    return transitions


def _collect_changelog_observations(changelog: dict | None) -> tuple[int, bool]:
    """Return touch_count and whether any status entries exist."""
    if not changelog:
        return 0, False

    histories = changelog.get("histories", [])
    has_status_entries = False

    for history in histories:
        for item in history.get("items", []):
            field = item.get("field")
            if field == "status":
                has_status_entries = True
            elif field:
                UNSUPPORTED_CHANGELOG_FIELDS.add(field)

    return len(histories), has_status_entries


def jira_issue_to_work_item(issue: dict) -> WorkItem:
    fields = issue["fields"]
    changelog = issue.get("changelog")

    touch_count, has_status_entries = _collect_changelog_observations(changelog)
    state_history = _extract_state_history(changelog)

    status_name = fields["status"]["name"]
    state = _map_status(status_name)
    state_confidence = (
        ConfidenceLevel.EXPLICIT
        if status_name in JIRA_STATUS_MAP
        else ConfidenceLevel.INFERRED
    )

    if changelog is None:
        state_history_confidence = ConfidenceLevel.MISSING
    elif has_status_entries:
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

    started_at: datetime | None = None
    for transition in state_history:
        if transition.to_state == CanonicalState.IN_PROGRESS:
            started_at = transition.transitioned_at
            break

    labels = fields.get("labels", [])
    is_blocked = True if any(label.lower() == "blocked" for label in labels) else None

    assignee_obj = fields.get("assignee")
    assignee = assignee_obj["displayName"] if assignee_obj else None

    priority_obj = fields.get("priority")
    priority = priority_obj["name"] if priority_obj else None

    parent_obj = fields.get("parent")
    parent_id = parent_obj["key"] if parent_obj else None

    sprint_id = _extract_sprint_id(fields)
    sprint_raw = fields.get("customfield_10020")

    field_confidence: dict[str, ConfidenceLevel] = {
        "state": state_confidence,
        "state_history": state_history_confidence,
        "touch_count": ConfidenceLevel.INFERRED,
        "age_in_state_days": ConfidenceLevel.INFERRED,
        "started_at": (
            ConfidenceLevel.INFERRED if started_at else ConfidenceLevel.MISSING
        ),
        "assignee": ConfidenceLevel.EXPLICIT if assignee else ConfidenceLevel.MISSING,
        "priority": ConfidenceLevel.EXPLICIT if priority else ConfidenceLevel.MISSING,
        "sprint_id": (
            ConfidenceLevel.EXPLICIT
            if sprint_raw is not None
            else ConfidenceLevel.MISSING
        ),
        "is_blocked": ConfidenceLevel.INFERRED,
    }

    return WorkItem(
        id=issue["key"],
        source_system="jira",
        source_url=f"https://imuasystems.atlassian.net/browse/{issue['key']}",
        item_type=fields["issuetype"]["name"],
        title=fields["summary"],
        labels=labels,
        state=state,
        state_changed_at=state_changed_at,
        state_history=state_history,
        priority=priority,
        assignee=assignee,
        created_at=_parse_datetime(fields["created"]),
        started_at=started_at,
        completed_at=(
            _parse_datetime(fields["resolutiondate"])
            if fields.get("resolutiondate")
            else None
        ),
        parent_id=parent_id,
        sprint_id=sprint_id,
        is_blocked=is_blocked,
        age_in_state_days=age_in_state_days,
        touch_count=touch_count,
        field_confidence=field_confidence,
    )


MRDN_25_SAMPLE = {
    "key": "MRDN-25",
    "changelog": {
        "histories": [
            {
                "id": "10103",
                "author": {"displayName": "Jim Martin"},
                "created": "2026-05-29T09:44:08.987-06:00",
                "items": [
                    {
                        "field": "Rank",
                        "fieldtype": "custom",
                        "fieldId": "customfield_10019",
                        "from": "",
                        "fromString": "",
                        "to": "",
                        "toString": "Ranked higher",
                    }
                ],
            },
            {
                "id": "10096",
                "author": {"displayName": "Jim Martin"},
                "created": "2026-05-29T09:44:06.739-06:00",
                "items": [
                    {
                        "field": "Sprint",
                        "fieldtype": "custom",
                        "fieldId": "customfield_10020",
                        "from": "",
                        "fromString": "",
                        "to": "1",
                        "toString": "SCRUM Sprint 2",
                    }
                ],
            },
            {
                "id": "10062",
                "author": {"displayName": "Jim Martin"},
                "created": "2026-05-29T09:34:53.238-06:00",
                "items": [
                    {
                        "field": "status",
                        "fieldtype": "jira",
                        "fieldId": "status",
                        "from": "10000",
                        "fromString": "To Do",
                        "to": "10001",
                        "toString": "In Progress",
                    }
                ],
            },
            {
                "id": "10047",
                "author": {"displayName": "Jim Martin"},
                "created": "2026-05-29T09:33:55.175-06:00",
                "items": [
                    {
                        "field": "IssueParentAssociation",
                        "fieldtype": "jira",
                        "from": None,
                        "fromString": None,
                        "to": "10007",
                        "toString": "MRDN-8",
                    }
                ],
            },
        ]
    },
    "fields": {
        "summary": "Pagination breaks when filter is applied on user list",
        "issuetype": {"name": "Bug"},
        "status": {"name": "In Progress"},
        "priority": {"name": "Medium"},
        "assignee": None,
        "created": "2026-05-29T09:33:55.141-06:00",
        "updated": "2026-05-29T09:44:08.987-06:00",
        "labels": ["bug-reduction"],
        "parent": {"key": "MRDN-8"},
        "customfield_10020": None,
        "resolutiondate": None,
    },
}


if __name__ == "__main__":
    work_item = jira_issue_to_work_item(MRDN_25_SAMPLE)
    print(json.dumps(work_item.model_dump(mode="json"), indent=2))
