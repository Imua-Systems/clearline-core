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
    PriorityChangeKind,
    PriorityTransition,
    SprintTransition,
    StateTransition,
    WorkItem,
)

# Jira changelog fields that represent prioritization signals. Backlog
# drag-and-drop reprioritization is emitted as "Rank" / customfield_10019,
# distinct from explicit "priority" field changes.
_RANK_CHANGELOG_FIELD_NAMES = {"rank"}
_RANK_CHANGELOG_FIELD_IDS = {"customfield_10019"}

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


def _current_sprint_entry(sprint_field) -> dict | str | None:
    """Return the sprint entry that best represents the issue's current sprint.

    Jira's sprint custom field is a list of every sprint an issue has been in.
    List order is not guaranteed, so when entries include ``state`` we prefer the
    last ``active`` sprint; otherwise we use the last list element (chronological
    append convention used when issues are moved between sprints).
    """
    if not sprint_field:
        return None
    if isinstance(sprint_field, dict):
        return sprint_field
    if isinstance(sprint_field, str):
        return sprint_field
    if not isinstance(sprint_field, list) or not sprint_field:
        return None

    dict_entries = [entry for entry in sprint_field if isinstance(entry, dict)]
    if dict_entries:
        active_entries = [
            entry for entry in dict_entries if entry.get("state") == "active"
        ]
        if active_entries:
            return active_entries[-1]
        return dict_entries[-1]

    for entry in reversed(sprint_field):
        if isinstance(entry, str):
            return entry
    return None


def _extract_sprint_id(fields: dict) -> str | None:
    entry = _current_sprint_entry(fields.get("customfield_10020"))
    if entry is None:
        return None
    if isinstance(entry, dict):
        sprint_id = entry.get("id")
        return str(sprint_id) if sprint_id is not None else None
    return None


def _extract_sprint_name(fields: dict) -> str | None:
    entry = _current_sprint_entry(fields.get("customfield_10020"))
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry.get("name")
    return str(entry)


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


def _normalize_sprint_changelog_label(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    stripped = value.strip()
    return stripped if stripped else None


def _changelog_author_name(history: dict) -> str | None:
    author = history.get("author") or {}
    return author.get("displayName") or author.get("accountId")


def _extract_sprint_history(changelog: dict | None) -> list[SprintTransition]:
    if not changelog:
        return []

    transitions: list[SprintTransition] = []

    for history in changelog.get("histories", []):
        has_sprint = any(
            item.get("field") == "Sprint" for item in history.get("items", [])
        )
        if not has_sprint:
            continue

        transitioned_at = _parse_datetime(history["created"])
        transitioned_by = _changelog_author_name(history)

        for item in history.get("items", []):
            if item.get("field") != "Sprint":
                continue

            transitions.append(
                SprintTransition(
                    from_sprint=_normalize_sprint_changelog_label(
                        item.get("fromString")
                    ),
                    to_sprint=_normalize_sprint_changelog_label(item.get("toString")),
                    transitioned_at=transitioned_at,
                    transitioned_by=transitioned_by,
                )
            )

    transitions.sort(key=lambda t: t.transitioned_at)
    return transitions


def _priority_change_kind(item: dict) -> PriorityChangeKind | None:
    """Classify a changelog item as a priority or rank signal.

    Returns the canonical ``PriorityChangeKind`` for prioritization-relevant
    changelog items, or ``None`` for items that are neither priority nor rank.

    - Explicit priority field changes match Jira field ``priority``.
    - Backlog rank/order movement matches field ``Rank`` and/or the
      ``customfield_10019`` field id (Jira emits both for drag-and-drop
      reprioritization).
    """
    field = (item.get("field") or "").lower()
    field_id = (item.get("fieldId") or "").lower()

    if field == "priority":
        return PriorityChangeKind.PRIORITY
    if field in _RANK_CHANGELOG_FIELD_NAMES or field_id in _RANK_CHANGELOG_FIELD_IDS:
        return PriorityChangeKind.RANK
    return None


def _extract_priority_history(changelog: dict | None) -> list[PriorityTransition]:
    if not changelog:
        return []

    transitions: list[PriorityTransition] = []

    for history in changelog.get("histories", []):
        matching_items = [
            (item, kind)
            for item in history.get("items", [])
            if (kind := _priority_change_kind(item)) is not None
        ]
        if not matching_items:
            continue

        transitioned_at = _parse_datetime(history["created"])
        transitioned_by = _changelog_author_name(history)

        for item, kind in matching_items:
            transitions.append(
                PriorityTransition(
                    from_priority=_normalize_sprint_changelog_label(
                        item.get("fromString")
                    ),
                    to_priority=_normalize_sprint_changelog_label(item.get("toString")),
                    transitioned_at=transitioned_at,
                    transitioned_by=transitioned_by,
                    change_kind=kind,
                    source_field=item.get("field"),
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
            elif _priority_change_kind(item) is not None:
                # priority and rank changes are consumed by priority history
                continue
            elif field:
                UNSUPPORTED_CHANGELOG_FIELDS.add(field)

    return len(histories), has_status_entries


def jira_issue_to_work_item(issue: dict) -> WorkItem:
    fields = issue["fields"]
    changelog = issue.get("changelog")

    touch_count, has_status_entries = _collect_changelog_observations(changelog)
    state_history = _extract_state_history(changelog)
    sprint_history = _extract_sprint_history(changelog)
    priority_history = _extract_priority_history(changelog)

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

    if changelog is None:
        sprint_history_confidence = ConfidenceLevel.MISSING
    elif sprint_history:
        sprint_history_confidence = ConfidenceLevel.EXPLICIT
    else:
        sprint_history_confidence = ConfidenceLevel.MISSING

    if changelog is None:
        priority_history_confidence = ConfidenceLevel.MISSING
    elif priority_history:
        priority_history_confidence = ConfidenceLevel.EXPLICIT
    else:
        priority_history_confidence = ConfidenceLevel.MISSING

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

    sprint_id = _extract_sprint_name(fields)
    sprint_raw = fields.get("customfield_10020")

    field_confidence: dict[str, ConfidenceLevel] = {
        "state": state_confidence,
        "state_history": state_history_confidence,
        "sprint_history": sprint_history_confidence,
        "priority_history": priority_history_confidence,
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
        sprint_history=sprint_history,
        priority_history=priority_history,
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


def _mapped_is_blocked(issue: dict) -> bool | None:
    labels = issue.get("labels", [])
    if any(label.lower() == "blocker" for label in labels):
        return True
    blocked = issue.get("blocked", False)
    return True if blocked else None


def mapped_issue_to_work_item(issue: dict) -> WorkItem:
    """Transform a flattened jira_client._map_issue() dict into a WorkItem."""
    status_name = issue.get("status", "")
    state = _map_status(status_name)
    state_confidence = (
        ConfidenceLevel.EXPLICIT
        if status_name in JIRA_STATUS_MAP
        else ConfidenceLevel.INFERRED
    )

    labels = issue.get("labels", [])
    assignee = issue.get("assignee")
    priority = issue.get("priority")
    sprint_id = issue.get("sprint")
    epic_key = issue.get("epic_key")
    epic_name = issue.get("epic_name")
    parent_id = epic_key or epic_name

    if epic_key:
        parent_confidence = ConfidenceLevel.EXPLICIT
    elif epic_name:
        parent_confidence = ConfidenceLevel.INFERRED
    else:
        parent_confidence = ConfidenceLevel.MISSING

    field_confidence: dict[str, ConfidenceLevel] = {
        "state": state_confidence,
        "state_history": ConfidenceLevel.MISSING,
        "sprint_history": ConfidenceLevel.MISSING,
        "priority_history": ConfidenceLevel.MISSING,
        "touch_count": ConfidenceLevel.MISSING,
        "age_in_state_days": ConfidenceLevel.MISSING,
        "started_at": ConfidenceLevel.MISSING,
        "state_changed_at": ConfidenceLevel.INFERRED,
        "assignee": ConfidenceLevel.EXPLICIT if assignee else ConfidenceLevel.MISSING,
        "priority": ConfidenceLevel.EXPLICIT if priority else ConfidenceLevel.MISSING,
        "sprint_id": ConfidenceLevel.EXPLICIT if sprint_id else ConfidenceLevel.MISSING,
        "is_blocked": ConfidenceLevel.INFERRED,
        "parent_id": parent_confidence,
    }

    return WorkItem(
        id=issue["key"],
        source_system="jira",
        source_url=f"https://imuasystems.atlassian.net/browse/{issue['key']}",
        item_type=issue.get("issue_type"),
        title=issue.get("summary"),
        labels=labels,
        state=state,
        state_changed_at=issue.get("updated"),
        state_history=[],
        priority=priority,
        assignee=assignee,
        created_at=issue["created"],
        started_at=None,
        completed_at=issue.get("resolved"),
        parent_id=parent_id,
        sprint_id=sprint_id,
        is_blocked=_mapped_is_blocked(issue),
        age_in_state_days=None,
        touch_count=None,
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
