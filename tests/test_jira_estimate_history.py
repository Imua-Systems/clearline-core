"""Tests for Jira story-points (customfield_10016) estimate history extraction."""

from clearline.adapters.jira import (
    UNSUPPORTED_CHANGELOG_FIELDS,
    _collect_changelog_observations,
    _extract_estimate_history,
    jira_issue_to_work_item,
)
from clearline.ontology.v1.core import ConfidenceLevel


def _estimate_item(
    *,
    from_string: str | None = "",
    to_string: str | None = "",
    field: str = "Story Points",
    field_id: str = "customfield_10016",
) -> dict:
    return {
        "field": field,
        "fieldtype": "custom",
        "fieldId": field_id,
        "from": from_string if from_string else None,
        "fromString": from_string,
        "to": to_string if to_string else None,
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


def _issue(
    histories: list[dict] | None,
    *,
    key: str = "IMUA-135",
    estimate=None,
) -> dict:
    issue = {
        "key": key,
        "fields": {
            "summary": "Estimate history test",
            "issuetype": {"name": "Story"},
            "status": {"name": "In Progress"},
            "priority": {"name": "Medium"},
            "assignee": None,
            "created": "2026-05-29T09:33:55.141-06:00",
            "updated": "2026-05-29T09:44:08.987-06:00",
            "labels": [],
            "parent": None,
            "customfield_10020": None,
            "customfield_10016": estimate,
            "resolutiondate": None,
        },
    }
    if histories is not None:
        issue["changelog"] = {"histories": histories}
    return issue


def test_estimate_history_increased():
    histories = [
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [_estimate_item(from_string="3", to_string="5")],
        )
    ]
    work_item = jira_issue_to_work_item(_issue(histories, estimate=5))

    assert len(work_item.estimate_history) == 1
    transition = work_item.estimate_history[0]
    assert transition.from_value == 3.0
    assert transition.to_value == 5.0
    assert transition.transitioned_by == "Jim Martin"
    assert transition.source_field == "Story Points"
    assert work_item.estimate == 5.0
    assert work_item.field_confidence["estimate_history"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["estimate"] == ConfidenceLevel.EXPLICIT


def test_estimate_history_decreased():
    histories = [
        _history(
            "1",
            "2026-06-17T08:20:57.635-06:00",
            [_estimate_item(from_string="8", to_string="3")],
        )
    ]
    work_item = jira_issue_to_work_item(_issue(histories, estimate=3))

    assert len(work_item.estimate_history) == 1
    transition = work_item.estimate_history[0]
    assert transition.from_value == 8.0
    assert transition.to_value == 3.0
    assert work_item.field_confidence["estimate_history"] == ConfidenceLevel.EXPLICIT


def test_estimate_history_repeated_changes():
    histories = [
        _history(
            "3",
            "2026-06-20T09:00:00.000-06:00",
            [_estimate_item(from_string="5", to_string="8")],
        ),
        _history(
            "2",
            "2026-06-15T14:00:00.000-06:00",
            [_estimate_item(from_string="3", to_string="5")],
        ),
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [_estimate_item(from_string="2", to_string="3")],
        ),
    ]
    work_item = jira_issue_to_work_item(_issue(histories, estimate=8))

    assert len(work_item.estimate_history) == 3
    assert work_item.estimate_history[0].from_value == 2.0
    assert work_item.estimate_history[0].to_value == 3.0
    assert work_item.estimate_history[1].from_value == 3.0
    assert work_item.estimate_history[1].to_value == 5.0
    assert work_item.estimate_history[2].from_value == 5.0
    assert work_item.estimate_history[2].to_value == 8.0
    assert work_item.field_confidence["estimate_history"] == ConfidenceLevel.EXPLICIT


def test_estimate_history_multiple_transitions_in_one_changelog_entry():
    histories = [
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [
                _estimate_item(from_string="2", to_string="5"),
                {
                    "field": "status",
                    "fieldtype": "jira",
                    "fieldId": "status",
                    "from": "10000",
                    "fromString": "To Do",
                    "to": "10001",
                    "toString": "In Progress",
                },
                _estimate_item(from_string="5", to_string="8"),
            ],
        )
    ]
    work_item = jira_issue_to_work_item(_issue(histories, estimate=8))

    assert len(work_item.estimate_history) == 2
    assert work_item.estimate_history[0].from_value == 2.0
    assert work_item.estimate_history[0].to_value == 5.0
    assert work_item.estimate_history[1].from_value == 5.0
    assert work_item.estimate_history[1].to_value == 8.0
    assert work_item.field_confidence["estimate_history"] == ConfidenceLevel.EXPLICIT


def test_estimate_history_null_to_value():
    histories = [
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [_estimate_item(from_string=None, to_string="5")],
        )
    ]
    transitions = _extract_estimate_history({"histories": histories})

    assert len(transitions) == 1
    assert transitions[0].from_value is None
    assert transitions[0].to_value == 5.0


def test_estimate_history_value_to_null():
    histories = [
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [_estimate_item(from_string="5", to_string=None)],
        )
    ]
    transitions = _extract_estimate_history({"histories": histories})

    assert len(transitions) == 1
    assert transitions[0].from_value == 5.0
    assert transitions[0].to_value is None


def test_estimate_history_empty_but_evaluated_is_explicit():
    """Changelog present with no estimate entries → EXPLICIT empty list."""
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

    assert work_item.estimate_history == []
    assert work_item.field_confidence["estimate_history"] == ConfidenceLevel.EXPLICIT


def test_estimate_history_missing_when_changelog_absent():
    work_item = jira_issue_to_work_item(_issue(None))

    assert work_item.estimate_history == []
    assert work_item.field_confidence["estimate_history"] == ConfidenceLevel.MISSING


def test_estimate_history_matched_by_field_id_only():
    histories = [
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [
                _estimate_item(
                    field="",
                    field_id="customfield_10016",
                    from_string="1",
                    to_string="2",
                )
            ],
        )
    ]
    transitions = _extract_estimate_history({"histories": histories})

    assert len(transitions) == 1
    assert transitions[0].from_value == 1.0
    assert transitions[0].to_value == 2.0
    assert transitions[0].source_field == "customfield_10016"


def test_current_estimate_missing_when_unset():
    work_item = jira_issue_to_work_item(_issue([], estimate=None))

    assert work_item.estimate is None
    assert work_item.field_confidence["estimate"] == ConfidenceLevel.MISSING
    assert work_item.field_confidence["estimate_history"] == ConfidenceLevel.EXPLICIT


def test_estimate_change_not_reported_as_unsupported_field():
    histories = [
        _history(
            "1",
            "2026-06-01T10:00:00.000-06:00",
            [_estimate_item(from_string="3", to_string="5")],
        )
    ]
    UNSUPPORTED_CHANGELOG_FIELDS.clear()
    _collect_changelog_observations({"histories": histories})

    assert "Story Points" not in UNSUPPORTED_CHANGELOG_FIELDS
