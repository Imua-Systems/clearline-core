"""
ADO work item adapter for Clearline ontology v1.

Transforms raw ADO Work Items API responses (with revision history) into canonical WorkItems.
This is the only module that references ADO-specific concepts.
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

ADO_STATE_MAP: dict[str, CanonicalState] = {
    "New": CanonicalState.BACKLOG,
    "Approved": CanonicalState.READY,
    "Committed": CanonicalState.IN_PROGRESS,
    "Active": CanonicalState.IN_PROGRESS,
    "In Progress": CanonicalState.IN_PROGRESS,
    "In Review": CanonicalState.REVIEW,
    "Resolved": CanonicalState.REVIEW,
    "Done": CanonicalState.DONE,
    "Closed": CanonicalState.DONE,
    "Removed": CanonicalState.ABANDONED,
}

UNMAPPED_STATUSES: set[str] = set()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _map_state(state: str | None) -> CanonicalState:
    if state and state in ADO_STATE_MAP:
        return ADO_STATE_MAP[state]
    if state:
        UNMAPPED_STATUSES.add(state)
    return CanonicalState.BACKLOG


def _parse_tags(tags: str | None) -> list[str]:
    if not tags:
        return []
    return [tag.strip() for tag in tags.split(";") if tag.strip()]


def _extract_parent_id(item: dict) -> str | None:
    for relation in item.get("relations") or []:
        if relation.get("rel") != "System.LinkTypes.Hierarchy-Reverse":
            continue
        url = relation.get("url", "")
        if url:
            return url.rstrip("/").split("/")[-1]
    return None


def _revision_timestamp(revision: dict) -> str | None:
    fields = revision.get("fields") or {}
    return revision.get("revisedDate") or fields.get("System.ChangedDate")


def _sorted_revisions(revisions: list[dict] | None) -> list[dict]:
    if not revisions:
        return []
    return sorted(revisions, key=lambda revision: _revision_timestamp(revision) or "")


def _extract_state_history(
    revisions: list[dict] | None,
) -> tuple[list[StateTransition], bool]:
    if not revisions:
        return [], False

    transitions: list[StateTransition] = []
    has_state_changes = False
    prev_state: str | None = None

    for revision in _sorted_revisions(revisions):
        try:
            fields = revision.get("fields", {})
            current_state = fields.get("System.State")
            if current_state is None:
                continue

            if prev_state is not None and current_state != prev_state:
                revised_at = _revision_timestamp(revision)
                if not revised_at:
                    logger.warning(
                        "Skipping state transition for revision %s: no timestamp",
                        revision.get("id", revision.get("rev", "?")),
                    )
                    prev_state = current_state
                    continue

                has_state_changes = True

                if prev_state not in ADO_STATE_MAP:
                    UNMAPPED_STATUSES.add(prev_state)
                if current_state not in ADO_STATE_MAP:
                    UNMAPPED_STATUSES.add(current_state)

                changed_by = fields.get("System.ChangedBy")
                transitioned_by = (
                    changed_by.get("displayName")
                    if isinstance(changed_by, dict)
                    else None
                )

                transitions.append(
                    StateTransition(
                        from_state=ADO_STATE_MAP.get(prev_state),
                        to_state=ADO_STATE_MAP.get(current_state, CanonicalState.BACKLOG),
                        transitioned_at=_parse_datetime(revised_at),
                        transitioned_by=transitioned_by,
                        source_status=current_state,
                    )
                )

            prev_state = current_state
        except Exception as exc:
            logger.warning(
                "Skipping revision %s during state history extraction: %s",
                revision.get("id", revision.get("rev", "?")),
                exc,
            )
            continue

    return transitions, has_state_changes


def _derive_started_at(revisions: list[dict] | None) -> datetime | None:
    for revision in _sorted_revisions(revisions):
        try:
            state = revision.get("fields", {}).get("System.State")
            if state and ADO_STATE_MAP.get(state) == CanonicalState.IN_PROGRESS:
                revised_at = _revision_timestamp(revision)
                if revised_at:
                    return _parse_datetime(revised_at)
        except Exception as exc:
            logger.warning(
                "Skipping revision %s during started_at derivation: %s",
                revision.get("id", revision.get("rev", "?")),
                exc,
            )
            continue
    return None


def ado_work_item_to_work_item(
    item: dict, revisions: list[dict] | None = None
) -> WorkItem:
    fields = item["fields"]

    state_history, has_state_changes = _extract_state_history(revisions)
    touch_count = len(revisions) if revisions else 0

    state_name = fields["System.State"]
    state = _map_state(state_name)
    state_confidence = (
        ConfidenceLevel.EXPLICIT
        if state_name in ADO_STATE_MAP
        else ConfidenceLevel.INFERRED
    )

    if revisions is None:
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

    started_at = _derive_started_at(revisions)

    links = item.get("_links") or {}
    html_link = links.get("html") or {}
    source_url = html_link.get("href")

    assignee_obj = fields.get("System.AssignedTo")
    assignee = assignee_obj["displayName"] if assignee_obj else None

    priority_value = fields.get("Microsoft.VSTS.Common.Priority")
    priority = str(priority_value) if priority_value is not None else None

    labels = _parse_tags(fields.get("System.Tags"))
    parent_id = _extract_parent_id(item)

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
        "parent_id": ConfidenceLevel.EXPLICIT if parent_id else ConfidenceLevel.MISSING,
    }

    return WorkItem(
        id=str(item["id"]),
        source_system="ado",
        source_url=source_url,
        item_type=fields["System.WorkItemType"],
        title=fields["System.Title"],
        labels=labels,
        state=state,
        state_changed_at=state_changed_at,
        state_history=state_history,
        priority=priority,
        assignee=assignee,
        created_at=_parse_datetime(fields["System.CreatedDate"]),
        started_at=started_at,
        parent_id=parent_id,
        age_in_state_days=age_in_state_days,
        touch_count=touch_count,
        field_confidence=field_confidence,
    )


MERIDIAN_SAMPLE = {
    "id": 42,
    "_links": {
        "html": {
            "href": "https://dev.azure.com/meridian/Platform/_workitems/edit/42"
        }
    },
    "fields": {
        "System.WorkItemType": "Bug",
        "System.Title": "Pagination breaks when filter is applied on user list",
        "System.State": "Active",
        "System.CreatedDate": "2026-05-29T09:33:55.141-06:00",
        "System.AssignedTo": {"displayName": "Jim Martin"},
        "Microsoft.VSTS.Common.Priority": 2,
        "System.Tags": "bug-reduction; frontend",
    },
    "relations": [
        {
            "rel": "System.LinkTypes.Hierarchy-Reverse",
            "url": "https://dev.azure.com/meridian/Platform/_apis/wit/workItems/8",
        }
    ],
}

MERIDIAN_SAMPLE_REVISIONS = [
    {
        "rev": 1,
        "revisedDate": "2026-05-29T09:33:55.141-06:00",
        "fields": {
            "System.State": "New",
            "System.ChangedBy": {"displayName": "Jim Martin"},
        },
    },
    {
        "rev": 2,
        "revisedDate": "2026-05-29T09:34:53.238-06:00",
        "fields": {
            "System.State": "Committed",
            "System.ChangedBy": {"displayName": "Jim Martin"},
        },
    },
    {
        "rev": 3,
        "revisedDate": "2026-05-29T09:44:06.739-06:00",
        "fields": {
            "System.State": "Active",
            "System.ChangedBy": {"displayName": "Jim Martin"},
        },
    },
]


if __name__ == "__main__":
    work_item = ado_work_item_to_work_item(MERIDIAN_SAMPLE, MERIDIAN_SAMPLE_REVISIONS)
    print(json.dumps(work_item.model_dump(mode="json"), indent=2))
