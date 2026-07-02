"""Tests for Jira priority changelog history extraction."""

from clearline.adapters.jira import (
    _extract_priority_history,
    jira_issue_to_work_item,
)
from clearline.ontology.v1.core import ConfidenceLevel


def _priority_item(
    *,
    from_string: str | None = "",
    to_string: str | None = "",
) -> dict:
    return {
        "field": "priority",
        "fieldtype": "jira",
        "fieldId": "priority",
        "from": "2" if from_string else "",
        "fromString": from_string,
        "to": "3" if to_string else "",
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


def _issue(histories: list[dict] | None, *, key: str = "IMUA-100") -> dict:
    issue = {
        "key": key,
        "fields": {
            "summary": "Priority test issue",
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


def test_priority_history_increased():
    histories = [
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [_priority_item(from_string="Medium", to_string="High")],
        )
    ]
    work_item = jira_issue_to_work_item(_issue(histories))

    assert len(work_item.priority_history) == 1
    transition = work_item.priority_history[0]
    assert transition.from_priority == "Medium"
    assert transition.to_priority == "High"
    assert transition.transitioned_by == "Jim Martin"
    assert work_item.field_confidence["priority_history"] == ConfidenceLevel.EXPLICIT


def test_priority_history_decreased():
    histories = [
        _history(
            "1",
            "2026-06-17T08:20:57.635-06:00",
            [_priority_item(from_string="High", to_string="Medium")],
        )
    ]
    work_item = jira_issue_to_work_item(_issue(histories))

    assert len(work_item.priority_history) == 1
    transition = work_item.priority_history[0]
    assert transition.from_priority == "High"
    assert transition.to_priority == "Medium"
    assert work_item.field_confidence["priority_history"] == ConfidenceLevel.EXPLICIT


def test_priority_history_multiple_transitions():
    histories = [
        _history(
            "2",
            "2026-06-15T14:00:00.000-06:00",
            [_priority_item(from_string="High", to_string="Medium")],
        ),
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [_priority_item(from_string="Medium", to_string="High")],
        ),
    ]
    work_item = jira_issue_to_work_item(_issue(histories))

    assert len(work_item.priority_history) == 2
    assert work_item.priority_history[0].from_priority == "Medium"
    assert work_item.priority_history[0].to_priority == "High"
    assert work_item.priority_history[1].from_priority == "High"
    assert work_item.priority_history[1].to_priority == "Medium"
    assert work_item.field_confidence["priority_history"] == ConfidenceLevel.EXPLICIT


def test_priority_history_missing_from_string():
    histories = [
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [_priority_item(from_string=None, to_string="High")],
        )
    ]
    transitions = _extract_priority_history({"histories": histories})

    assert len(transitions) == 1
    assert transitions[0].from_priority is None
    assert transitions[0].to_priority == "High"


def test_priority_history_missing_to_string():
    histories = [
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [_priority_item(from_string="High", to_string=None)],
        )
    ]
    transitions = _extract_priority_history({"histories": histories})

    assert len(transitions) == 1
    assert transitions[0].from_priority == "High"
    assert transitions[0].to_priority is None


def test_priority_history_empty_when_no_priority_changelog_entries():
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

    assert work_item.priority_history == []
    assert work_item.field_confidence["priority_history"] == ConfidenceLevel.MISSING


def test_priority_history_missing_when_changelog_absent():
    work_item = jira_issue_to_work_item(_issue(None))

    assert work_item.priority_history == []
    assert work_item.field_confidence["priority_history"] == ConfidenceLevel.MISSING


def test_priority_history_matches_case_insensitive_field_name():
    histories = [
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [
                {
                    "field": "Priority",
                    "fieldtype": "jira",
                    "fieldId": "priority",
                    "from": "2",
                    "fromString": "High",
                    "to": "3",
                    "toString": "Medium",
                }
            ],
        )
    ]
    work_item = jira_issue_to_work_item(_issue(histories))

    assert len(work_item.priority_history) == 1
    assert work_item.priority_history[0].from_priority == "High"
    assert work_item.priority_history[0].to_priority == "Medium"
