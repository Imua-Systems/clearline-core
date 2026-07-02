"""Tests for Jira sprint changelog history extraction."""

from clearline.adapters.jira import (
    MRDN_25_SAMPLE,
    _extract_sprint_history,
    jira_issue_to_work_item,
)
from clearline.ontology.v1.core import ConfidenceLevel


def _sprint_item(
    *,
    from_string: str | None = "",
    to_string: str | None = "",
) -> dict:
    return {
        "field": "Sprint",
        "fieldtype": "custom",
        "fieldId": "customfield_10020",
        "from": "",
        "fromString": from_string,
        "to": "",
        "toString": to_string,
    }


def _history(
    history_id: str,
    created: str,
    items: list[dict],
    *,
    author: str = "Jim Martin",
) -> dict:
    return {
        "id": history_id,
        "author": {"displayName": author, "accountId": "abc123"},
        "created": created,
        "items": items,
    }


def _issue(histories: list[dict] | None, *, key: str = "MRDN-100") -> dict:
    issue = {
        "key": key,
        "fields": {
            "summary": "Sprint history test",
            "issuetype": {"name": "Story"},
            "status": {"name": "In Progress"},
            "priority": {"name": "Medium"},
            "assignee": None,
            "created": "2026-05-29T09:33:55.141-06:00",
            "updated": "2026-05-29T09:44:08.987-06:00",
            "labels": [],
            "parent": None,
            "customfield_10020": None,
            "resolutiondate": None,
        },
    }
    if histories is not None:
        issue["changelog"] = {"histories": histories}
    return issue


def test_sprint_history_issue_added_to_sprint():
    histories = [
        _history(
            "1",
            "2026-05-29T09:40:00.000-06:00",
            [_sprint_item(from_string="", to_string="SCRUM Sprint 1")],
        )
    ]
    work_item = jira_issue_to_work_item(_issue(histories))

    assert len(work_item.sprint_history) == 1
    transition = work_item.sprint_history[0]
    assert transition.from_sprint is None
    assert transition.to_sprint == "SCRUM Sprint 1"
    assert transition.transitioned_by == "Jim Martin"
    assert work_item.field_confidence["sprint_history"] == ConfidenceLevel.EXPLICIT


def test_sprint_history_issue_removed_from_sprint():
    histories = [
        _history(
            "1",
            "2026-05-29T09:40:00.000-06:00",
            [_sprint_item(from_string="SCRUM Sprint 1", to_string="")],
        )
    ]
    work_item = jira_issue_to_work_item(_issue(histories))

    assert len(work_item.sprint_history) == 1
    transition = work_item.sprint_history[0]
    assert transition.from_sprint == "SCRUM Sprint 1"
    assert transition.to_sprint is None
    assert work_item.field_confidence["sprint_history"] == ConfidenceLevel.EXPLICIT


def test_sprint_history_issue_moved_between_sprints():
    histories = [
        _history(
            "1",
            "2026-05-29T09:40:00.000-06:00",
            [
                _sprint_item(
                    from_string="SCRUM Sprint 1",
                    to_string="SCRUM Sprint 2",
                )
            ],
        )
    ]
    work_item = jira_issue_to_work_item(_issue(histories))

    assert len(work_item.sprint_history) == 1
    transition = work_item.sprint_history[0]
    assert transition.from_sprint == "SCRUM Sprint 1"
    assert transition.to_sprint == "SCRUM Sprint 2"


def test_sprint_history_preserves_chronological_order():
    histories = [
        _history(
            "2",
            "2026-05-29T09:44:06.739-06:00",
            [
                _sprint_item(
                    from_string="SCRUM Sprint 1",
                    to_string="SCRUM Sprint 2",
                )
            ],
        ),
        _history(
            "1",
            "2026-05-29T09:40:00.000-06:00",
            [_sprint_item(from_string="", to_string="SCRUM Sprint 1")],
        ),
    ]
    work_item = jira_issue_to_work_item(_issue(histories))

    assert len(work_item.sprint_history) == 2
    assert work_item.sprint_history[0].to_sprint == "SCRUM Sprint 1"
    assert work_item.sprint_history[1].from_sprint == "SCRUM Sprint 1"
    assert work_item.sprint_history[1].to_sprint == "SCRUM Sprint 2"


def test_sprint_history_empty_when_no_sprint_changelog_entries():
    histories = [
        _history(
            "1",
            "2026-05-29T09:34:53.238-06:00",
            [
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
        )
    ]
    work_item = jira_issue_to_work_item(_issue(histories))

    assert work_item.sprint_history == []
    assert work_item.field_confidence["sprint_history"] == ConfidenceLevel.MISSING


def test_sprint_history_missing_when_changelog_absent():
    work_item = jira_issue_to_work_item(_issue(None))

    assert work_item.sprint_history == []
    assert work_item.field_confidence["sprint_history"] == ConfidenceLevel.MISSING


def test_sprint_history_handles_null_from_string_and_to_string():
    histories = [
        _history(
            "1",
            "2026-05-29T09:40:00.000-06:00",
            [
                {
                    "field": "Sprint",
                    "fieldtype": "custom",
                    "fieldId": "customfield_10020",
                    "from": None,
                    "fromString": None,
                    "to": "1",
                    "toString": "SCRUM Sprint 1",
                }
            ],
        )
    ]
    transitions = _extract_sprint_history({"histories": histories})

    assert len(transitions) == 1
    assert transitions[0].from_sprint is None
    assert transitions[0].to_sprint == "SCRUM Sprint 1"


def test_mrdn_25_sample_extracts_sprint_add_transition():
    work_item = jira_issue_to_work_item(MRDN_25_SAMPLE)

    assert len(work_item.sprint_history) == 1
    assert work_item.sprint_history[0].from_sprint is None
    assert work_item.sprint_history[0].to_sprint == "SCRUM Sprint 2"
    assert work_item.field_confidence["sprint_history"] == ConfidenceLevel.EXPLICIT
