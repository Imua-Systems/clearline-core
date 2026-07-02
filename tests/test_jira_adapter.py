"""Regression tests for Jira sprint extraction."""

from clearline.adapters.jira import (
    _extract_sprint_id,
    _extract_sprint_name,
    jira_issue_to_work_item,
)


def _sprint_fields(*entries) -> dict:
    return {"customfield_10020": list(entries)}


def test_sprint_extractors_agree_on_active_sprint():
    fields = _sprint_fields(
        {"id": 1, "name": "SCRUM Sprint 1", "state": "closed"},
        {"id": 2, "name": "SCRUM Sprint 2", "state": "active"},
    )

    assert _extract_sprint_id(fields) == "2"
    assert _extract_sprint_name(fields) == "SCRUM Sprint 2"


def test_sprint_extractors_agree_on_last_closed_sprint():
    fields = _sprint_fields(
        {"id": 1, "name": "SCRUM Sprint 1", "state": "closed"},
        {"id": 2, "name": "SCRUM Sprint 2", "state": "closed"},
    )

    assert _extract_sprint_id(fields) == "2"
    assert _extract_sprint_name(fields) == "SCRUM Sprint 2"


def test_sprint_extractors_prefer_last_active_when_multiple_active():
    fields = _sprint_fields(
        {"id": 1, "name": "SCRUM Sprint 1", "state": "active"},
        {"id": 2, "name": "SCRUM Sprint 2", "state": "active"},
    )

    assert _extract_sprint_id(fields) == "2"
    assert _extract_sprint_name(fields) == "SCRUM Sprint 2"


def test_sprint_extractors_ignore_non_active_when_later_in_list():
    fields = _sprint_fields(
        {"id": 2, "name": "SCRUM Sprint 2", "state": "active"},
        {"id": 1, "name": "SCRUM Sprint 1", "state": "closed"},
    )

    assert _extract_sprint_id(fields) == "2"
    assert _extract_sprint_name(fields) == "SCRUM Sprint 2"


def test_sprint_extractors_handle_single_sprint_dict():
    fields = {
        "customfield_10020": [
            {"id": 3, "name": "MRDN Sprint 2", "state": "active", "boardId": 1},
        ]
    }

    assert _extract_sprint_id(fields) == "3"
    assert _extract_sprint_name(fields) == "MRDN Sprint 2"


def test_sprint_extractors_handle_legacy_string_entries():
    fields = _sprint_fields("SCRUM Sprint 1", "SCRUM Sprint 2")

    assert _extract_sprint_id(fields) is None
    assert _extract_sprint_name(fields) == "SCRUM Sprint 2"


def test_jira_issue_to_work_item_uses_consistent_sprint_name():
    issue = {
        "key": "MRDN-99",
        "fields": {
            "summary": "Moved between sprints",
            "issuetype": {"name": "Story"},
            "status": {"name": "In Progress"},
            "priority": {"name": "Medium"},
            "assignee": None,
            "created": "2026-05-29T09:33:55.141-06:00",
            "updated": "2026-05-29T09:44:08.987-06:00",
            "labels": [],
            "parent": None,
            "customfield_10020": [
                {"id": 1, "name": "SCRUM Sprint 1", "state": "closed"},
                {"id": 2, "name": "SCRUM Sprint 2", "state": "active"},
            ],
            "resolutiondate": None,
        },
    }

    work_item = jira_issue_to_work_item(issue)

    assert work_item.sprint_id == "SCRUM Sprint 2"
