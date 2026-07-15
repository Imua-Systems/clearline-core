"""Tests for Jira sprint metadata normalization (IMUA-139).

Proves completeDate → complete_date mapping and that id, name, start_date,
end_date (planned), complete_date, and fetched_at survive Jira → ontology
normalization — including when completeDate is absent.
"""

from datetime import datetime, timezone

from clearline.adapters.jira import jira_sprint_to_sprint, sprint_to_closed_ref
from clearline.ontology.v1.core import ClosedSprintRef, Sprint, SprintContext


_FETCHED_AT = datetime(2026, 7, 15, 18, 0, 0, tzinfo=timezone.utc)


def _closed_jira_sprint() -> dict:
    return {
        "id": 37,
        "name": "SCRUM Sprint 1",
        "state": "closed",
        "boardId": 1,
        "startDate": "2026-04-01T15:22:00.000+00:00",
        "endDate": "2026-04-15T15:22:00.000+00:00",
        "completeDate": "2026-04-15T16:05:00.000+00:00",
    }


def _active_jira_sprint_without_complete() -> dict:
    return {
        "id": 42,
        "name": "SCRUM Sprint 2",
        "state": "active",
        "boardId": 1,
        "startDate": "2026-04-16T15:22:00.000+00:00",
        "endDate": "2026-04-30T15:22:00.000+00:00",
    }


def test_jira_sprint_with_complete_date_maps_all_six_fields():
    sprint = jira_sprint_to_sprint(_closed_jira_sprint(), fetched_at=_FETCHED_AT)

    assert sprint.id == "37"
    assert sprint.name == "SCRUM Sprint 1"
    assert sprint.state == "closed"
    assert sprint.start_date == datetime(2026, 4, 1, 15, 22, tzinfo=timezone.utc)
    assert sprint.end_date == datetime(2026, 4, 15, 15, 22, tzinfo=timezone.utc)
    assert sprint.complete_date == datetime(2026, 4, 15, 16, 5, tzinfo=timezone.utc)
    assert sprint.fetched_at == _FETCHED_AT


def test_jira_sprint_without_complete_date_preserves_none():
    sprint = jira_sprint_to_sprint(
        _active_jira_sprint_without_complete(),
        fetched_at=_FETCHED_AT,
    )

    assert sprint.id == "42"
    assert sprint.name == "SCRUM Sprint 2"
    assert sprint.state == "active"
    assert sprint.start_date == datetime(2026, 4, 16, 15, 22, tzinfo=timezone.utc)
    assert sprint.end_date == datetime(2026, 4, 30, 15, 22, tzinfo=timezone.utc)
    assert sprint.complete_date is None
    assert sprint.fetched_at == _FETCHED_AT


def test_jira_sprint_malformed_empty_complete_date_is_none():
    raw = _closed_jira_sprint()
    raw["completeDate"] = ""
    sprint = jira_sprint_to_sprint(raw, fetched_at=_FETCHED_AT)
    assert sprint.complete_date is None
    assert sprint.end_date == datetime(2026, 4, 15, 15, 22, tzinfo=timezone.utc)


def test_normalization_round_trip_each_field():
    """Each preserved field survives raw Jira → Sprint → ClosedSprintRef."""
    sprint = jira_sprint_to_sprint(_closed_jira_sprint(), fetched_at=_FETCHED_AT)
    ref = sprint_to_closed_ref(sprint)

    assert ref.id == "37"
    assert ref.name == "SCRUM Sprint 1"
    assert ref.start_date == sprint.start_date
    assert ref.end_date == sprint.end_date
    assert ref.complete_date == sprint.complete_date
    assert ref.fetched_at == sprint.fetched_at
    assert ref.state == "closed"


def test_closed_sprint_ref_preserves_six_fields_when_complete_absent():
    sprint = jira_sprint_to_sprint(
        _active_jira_sprint_without_complete(),
        fetched_at=_FETCHED_AT,
    )
    ref = sprint_to_closed_ref(sprint)

    assert ref.id == "42"
    assert ref.name == "SCRUM Sprint 2"
    assert ref.start_date is not None
    assert ref.end_date is not None
    assert ref.complete_date is None
    assert ref.fetched_at == _FETCHED_AT


def test_sprint_context_backward_compat_start_end_only():
    """Consumers constructing SprintContext with only start/end remain valid."""
    ctx = SprintContext(
        name="Sprint 24",
        start_date=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        end_date=datetime(2026, 6, 15, 17, 0, tzinfo=timezone.utc),
    )
    assert ctx.name == "Sprint 24"
    assert ctx.state == "active"
    assert ctx.start_date is not None
    assert ctx.end_date is not None
    assert ctx.id is None
    assert ctx.complete_date is None
    assert ctx.fetched_at is None
    assert ctx.closed_sprints == []


def test_closed_sprint_ref_backward_compat_name_end_only():
    """Existing ClosedSprintRef consumers using name/end_date only still work."""
    ref = ClosedSprintRef(
        name="Sprint 23",
        end_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    assert ref.name == "Sprint 23"
    assert ref.state == "closed"
    assert ref.end_date is not None
    assert ref.id is None
    assert ref.start_date is None
    assert ref.complete_date is None
    assert ref.fetched_at is None


def test_sprint_context_carries_complete_date_and_closed_refs():
    sprint = jira_sprint_to_sprint(_closed_jira_sprint(), fetched_at=_FETCHED_AT)
    ref = sprint_to_closed_ref(sprint)
    ctx = SprintContext(
        id=sprint.id,
        name=sprint.name,
        state=sprint.state or "closed",
        start_date=sprint.start_date,
        end_date=sprint.end_date,
        complete_date=sprint.complete_date,
        fetched_at=sprint.fetched_at,
        closed_sprints=[ref],
    )
    assert ctx.complete_date == sprint.complete_date
    assert ctx.fetched_at == _FETCHED_AT
    assert len(ctx.closed_sprints) == 1
    assert ctx.closed_sprints[0].complete_date == sprint.complete_date


def test_complete_date_distinct_from_planned_end_date():
    """completeDate must remain distinct from the mutable planned endDate."""
    sprint = jira_sprint_to_sprint(_closed_jira_sprint(), fetched_at=_FETCHED_AT)
    assert sprint.end_date != sprint.complete_date
    assert isinstance(sprint, Sprint)
