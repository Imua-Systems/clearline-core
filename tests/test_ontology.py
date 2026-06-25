from datetime import datetime, timezone
import json

from unittest.mock import MagicMock, patch

import pytest

from clearline.adapters.bitbucket import (
    BITBUCKET_FULL_SAMPLE,
    BITBUCKET_FULL_SAMPLE_CHANGES,
    BITBUCKET_MINIMAL_SAMPLE,
    BITBUCKET_STATE_MAP,
    bitbucket_issue_to_work_item,
)
from clearline.adapters.github_issues import (
    GITHUB_FULL_SAMPLE,
    GITHUB_FULL_SAMPLE_EVENTS,
    GITHUB_MINIMAL_SAMPLE,
    GITHUB_STATE_MAP,
    github_issue_to_work_item,
    is_github_issue,
)
from clearline.adapters.gitlab import (
    GITLAB_FULL_SAMPLE,
    GITLAB_FULL_SAMPLE_EVENTS,
    GITLAB_MINIMAL_SAMPLE,
    GITLAB_STATE_MAP,
    gitlab_issue_to_work_item,
)
from clearline.ontology.v1 import (
    CanonicalState,
    ConfidenceLevel,
    DiagnosticReliability,
    FailureModeDiagnostic,
    FieldMapping,
    MappingSet,
    MappingStatus,
    ReliabilityBand,
    StateTransition,
    WorkItem,
)


def test_canonical_state_values():
    assert CanonicalState.BACKLOG == "backlog"
    assert CanonicalState.READY == "ready"
    assert CanonicalState.IN_PROGRESS == "in_progress"
    assert CanonicalState.WAITING == "waiting"
    assert CanonicalState.BLOCKED == "blocked"
    assert CanonicalState.REVIEW == "review"
    assert CanonicalState.DONE == "done"
    assert CanonicalState.ABANDONED == "abandoned"


def test_confidence_level_values():
    assert ConfidenceLevel.EXPLICIT == "explicit"
    assert ConfidenceLevel.INFERRED == "inferred"
    assert ConfidenceLevel.MISSING == "missing"
    assert ConfidenceLevel.CONTRADICTED == "contradicted"


def test_work_item_minimal():
    item = WorkItem(
        id="TEST-1",
        source_system="jira",
        state=CanonicalState.BACKLOG,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert item.id == "TEST-1"
    assert item.source_system == "jira"
    assert item.state == CanonicalState.BACKLOG
    assert item.labels == []
    assert item.state_history == []
    assert item.field_confidence == {}
    assert item.touch_count is None
    assert item.assignee is None


def test_work_item_full():
    transition = StateTransition(
        from_state=CanonicalState.BACKLOG,
        to_state=CanonicalState.IN_PROGRESS,
        transitioned_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        transitioned_by="Jim Martin",
        source_status="In Progress",
    )
    item = WorkItem(
        id="TEST-2",
        source_system="jira",
        state=CanonicalState.IN_PROGRESS,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        state_history=[transition],
        touch_count=3,
        age_in_state_days=5.0,
        is_blocked=False,
        priority="High",
        assignee="Jim Martin",
        labels=["sprint-1"],
        field_confidence={
            "state": ConfidenceLevel.EXPLICIT,
            "touch_count": ConfidenceLevel.INFERRED,
            "assignee": ConfidenceLevel.EXPLICIT,
        },
    )
    assert len(item.state_history) == 1
    assert item.state_history[0].to_state == CanonicalState.IN_PROGRESS
    assert item.touch_count == 3
    assert item.field_confidence["state"] == ConfidenceLevel.EXPLICIT
    assert item.field_confidence["touch_count"] == ConfidenceLevel.INFERRED


def test_work_item_invalid_state():
    with pytest.raises(Exception):
        WorkItem(
            id="TEST-3",
            source_system="jira",
            state="not_a_real_state",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_field_mapping_proposed():
    mapping = FieldMapping(
        source_system="jira",
        source_field="customfield_10123",
        target_field="priority",
        confidence=0.82,
        confidence_level=ConfidenceLevel.INFERRED,
        rationale="Field appears to represent business priority based on value patterns",
        status=MappingStatus.PROPOSED,
        proposed_by="agent",
        proposed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert mapping.status == MappingStatus.PROPOSED
    assert mapping.validated_by is None
    assert mapping.validated_at is None
    assert mapping.confidence == 0.82


def test_field_mapping_validated():
    mapping = FieldMapping(
        source_system="jira",
        source_field="customfield_10123",
        target_field="priority",
        confidence=0.82,
        confidence_level=ConfidenceLevel.EXPLICIT,
        rationale="Confirmed by client admin",
        status=MappingStatus.VALIDATED,
        proposed_by="agent",
        proposed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        validated_by="jane.smith@client.com",
        validated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert mapping.status == MappingStatus.VALIDATED
    assert mapping.validated_by == "jane.smith@client.com"


def test_field_mapping_canonical():
    mapping = FieldMapping(
        source_system="jira",
        source_field="status",
        target_field="state",
        confidence=1.0,
        confidence_level=ConfidenceLevel.EXPLICIT,
        rationale="Native Jira status field maps directly to CanonicalState",
        status=MappingStatus.CANONICAL,
        proposed_by="imua",
        proposed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        validated_by="imua",
        validated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        canonicalized_by="imua",
        canonicalized_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert mapping.status == MappingStatus.CANONICAL
    assert mapping.canonicalized_by == "imua"


def test_mapping_set_coverage():
    mappings = [
        FieldMapping(
            source_system="jira",
            source_field="status",
            target_field="state",
            confidence=1.0,
            confidence_level=ConfidenceLevel.EXPLICIT,
            rationale="direct",
            status=MappingStatus.CANONICAL,
            proposed_by="imua",
            proposed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        FieldMapping(
            source_system="jira",
            source_field="created",
            target_field="created_at",
            confidence=1.0,
            confidence_level=ConfidenceLevel.EXPLICIT,
            rationale="direct",
            status=MappingStatus.VALIDATED,
            proposed_by="agent",
            proposed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            validated_by="user",
            validated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
        FieldMapping(
            source_system="jira",
            source_field="customfield_10020",
            target_field="sprint_id",
            confidence=0.9,
            confidence_level=ConfidenceLevel.INFERRED,
            rationale="sprint custom field",
            status=MappingStatus.PROPOSED,
            proposed_by="agent",
            proposed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    ]
    ms = MappingSet(
        id="ms-001",
        client_id="client-001",
        source_system="jira",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        mappings=mappings,
    )
    assert ms.validation_coverage == pytest.approx(2 / 3)


def test_mapping_set_field_coverage():
    mappings = [
        FieldMapping(
            source_system="jira",
            source_field="status",
            target_field="state",
            confidence=1.0,
            confidence_level=ConfidenceLevel.EXPLICIT,
            rationale="direct",
            status=MappingStatus.CANONICAL,
            proposed_by="imua",
            proposed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        FieldMapping(
            source_system="jira",
            source_field="created",
            target_field="created_at",
            confidence=1.0,
            confidence_level=ConfidenceLevel.EXPLICIT,
            rationale="direct",
            status=MappingStatus.VALIDATED,
            proposed_by="agent",
            proposed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            validated_by="user",
            validated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
        FieldMapping(
            source_system="jira",
            source_field="customfield_10020",
            target_field="sprint_id",
            confidence=0.9,
            confidence_level=ConfidenceLevel.INFERRED,
            rationale="sprint custom field",
            status=MappingStatus.PROPOSED,
            proposed_by="agent",
            proposed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    ]
    ms = MappingSet(
        id="ms-001",
        client_id="client-001",
        source_system="jira",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        mappings=mappings,
    )
    assert ms.coverage == pytest.approx(3 / 10)


def test_mapping_set_empty():
    ms = MappingSet(
        id="ms-empty",
        client_id="client-001",
        source_system="jira",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert ms.coverage == 0.0
    assert ms.validation_coverage == 0.0


def test_diagnostic_reliability_high():
    r = DiagnosticReliability.compute(
        data_coverage=0.95,
        transition_fidelity=0.90,
        mapping_confidence=0.92,
        temporal_completeness=0.88,
        cross_system_consistency=1.0,
        human_validation_coverage=0.85,
    )
    assert r.reliability_band == ReliabilityBand.HIGH
    assert r.reliability_score >= 0.80


def test_diagnostic_reliability_moderate():
    r = DiagnosticReliability.compute(
        data_coverage=0.70,
        transition_fidelity=0.60,
        mapping_confidence=0.65,
        temporal_completeness=0.60,
        cross_system_consistency=0.80,
        human_validation_coverage=0.50,
    )
    assert r.reliability_band == ReliabilityBand.MODERATE
    assert 0.55 <= r.reliability_score < 0.80


def test_diagnostic_reliability_low():
    r = DiagnosticReliability.compute(
        data_coverage=0.30,
        transition_fidelity=0.20,
        mapping_confidence=0.25,
        temporal_completeness=0.30,
        cross_system_consistency=0.40,
        human_validation_coverage=0.10,
    )
    assert r.reliability_band == ReliabilityBand.LOW
    assert r.reliability_score < 0.55


def test_diagnostic_reliability_boundary_high():
    r = DiagnosticReliability.compute(
        data_coverage=0.80,
        transition_fidelity=0.80,
        mapping_confidence=0.80,
        temporal_completeness=0.80,
        cross_system_consistency=0.80,
        human_validation_coverage=0.80,
    )
    assert r.reliability_band == ReliabilityBand.HIGH


def test_diagnostic_reliability_boundary_moderate():
    r = DiagnosticReliability.compute(
        data_coverage=0.55,
        transition_fidelity=0.55,
        mapping_confidence=0.55,
        temporal_completeness=0.55,
        cross_system_consistency=0.55,
        human_validation_coverage=0.55,
    )
    assert r.reliability_band == ReliabilityBand.MODERATE


def test_failure_mode_diagnostic_full():
    reliability = DiagnosticReliability.compute(
        data_coverage=0.85,
        transition_fidelity=0.60,
        mapping_confidence=0.78,
        temporal_completeness=0.70,
        cross_system_consistency=1.0,
        human_validation_coverage=0.50,
        limiting_factors=["Transition history missing for 17% of items"],
        improvement_actions=["Connect revision history endpoint"],
    )
    diagnostic = FailureModeDiagnostic(
        failure_mode="Leadership Entropy",
        score=81.0,
        band="High",
        reliability=reliability,
        evidence=["High touch count", "Frequent reassignment"],
        assumptions=["Blocked states inferred from labels"],
        recommended_next_observation=["Validate dependency field mappings"],
    )
    assert diagnostic.failure_mode == "Leadership Entropy"
    assert diagnostic.score == 81.0
    assert diagnostic.band == "High"
    assert diagnostic.reliability.reliability_band == ReliabilityBand.MODERATE
    assert len(diagnostic.evidence) == 2
    assert len(diagnostic.assumptions) == 1
    assert len(diagnostic.recommended_next_observation) == 1
    assert diagnostic.ontology_version == "clearline-ontology-v1.0"


def test_gitlab_issue_to_work_item_minimal():
    work_item = gitlab_issue_to_work_item(GITLAB_MINIMAL_SAMPLE)

    assert work_item.id == "25"
    assert work_item.source_system == "gitlab"
    assert work_item.item_type == "issue"
    assert work_item.title == GITLAB_MINIMAL_SAMPLE["title"]
    assert work_item.labels == ["bug-reduction"]
    assert work_item.state == CanonicalState.IN_PROGRESS
    assert work_item.state_history == []
    assert work_item.touch_count is None
    assert work_item.started_at is None
    assert work_item.completed_at is None
    assert work_item.field_confidence["state"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["state_history"] == ConfidenceLevel.MISSING
    assert work_item.field_confidence["touch_count"] == ConfidenceLevel.MISSING
    assert work_item.field_confidence["started_at"] == ConfidenceLevel.MISSING
    assert work_item.field_confidence["completed_at"] == ConfidenceLevel.MISSING


def test_gitlab_issue_to_work_item_full():
    work_item = gitlab_issue_to_work_item(GITLAB_FULL_SAMPLE, GITLAB_FULL_SAMPLE_EVENTS)

    assert work_item.id == "25"
    assert work_item.source_system == "gitlab"
    assert work_item.assignee == "jim.martin"
    assert work_item.sprint_id == "Sprint 2"
    assert work_item.is_blocked is True
    assert work_item.state == CanonicalState.DONE
    assert work_item.touch_count == 2
    assert len(work_item.state_history) == 1
    assert work_item.state_history[0].from_state == CanonicalState.IN_PROGRESS
    assert work_item.state_history[0].to_state == CanonicalState.DONE
    assert work_item.started_at is not None
    assert work_item.completed_at is not None
    assert work_item.field_confidence["state"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["state_history"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["touch_count"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["started_at"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["completed_at"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["assignee"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["sprint_id"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["is_blocked"] == ConfidenceLevel.INFERRED


def test_gitlab_state_map_opened_and_closed():
    assert GITLAB_STATE_MAP["opened"] == CanonicalState.IN_PROGRESS
    assert GITLAB_STATE_MAP["closed"] == CanonicalState.DONE

    opened_item = gitlab_issue_to_work_item(
        {**GITLAB_MINIMAL_SAMPLE, "state": "opened"},
        events=None,
    )
    closed_item = gitlab_issue_to_work_item(
        {**GITLAB_MINIMAL_SAMPLE, "state": "closed"},
        events=None,
    )

    assert opened_item.state == CanonicalState.IN_PROGRESS
    assert closed_item.state == CanonicalState.DONE


def test_gitlab_field_confidence_populated():
    work_item = gitlab_issue_to_work_item(GITLAB_FULL_SAMPLE, GITLAB_FULL_SAMPLE_EVENTS)

    expected_fields = {
        "state",
        "state_history",
        "touch_count",
        "age_in_state_days",
        "started_at",
        "completed_at",
        "assignee",
        "sprint_id",
        "is_blocked",
    }
    assert set(work_item.field_confidence.keys()) == expected_fields
    assert all(
        isinstance(level, ConfidenceLevel)
        for level in work_item.field_confidence.values()
    )


def test_github_issue_to_work_item_minimal():
    work_item = github_issue_to_work_item(GITHUB_MINIMAL_SAMPLE, events=[])

    assert work_item.id == "25"
    assert work_item.source_system == "github_issues"
    assert work_item.item_type == "issue"
    assert work_item.title == GITHUB_MINIMAL_SAMPLE["title"]
    assert work_item.labels == []
    assert work_item.state == CanonicalState.IN_PROGRESS
    assert work_item.assignee is None
    assert work_item.sprint_id is None
    assert work_item.priority is None
    assert work_item.parent_id is None
    assert work_item.state_history == []
    assert work_item.touch_count == 0
    assert work_item.started_at == work_item.created_at
    assert work_item.completed_at is None
    assert work_item.field_confidence["state"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["state_history"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["touch_count"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["started_at"] == ConfidenceLevel.INFERRED
    assert "assignee" not in work_item.field_confidence
    assert "sprint_id" not in work_item.field_confidence


def test_github_issue_to_work_item_full():
    work_item = github_issue_to_work_item(GITHUB_FULL_SAMPLE, GITHUB_FULL_SAMPLE_EVENTS)

    assert work_item.id == "25"
    assert work_item.source_system == "github_issues"
    assert work_item.assignee == "jim-martin"
    assert work_item.sprint_id == "Sprint 2"
    assert work_item.labels == ["bug-reduction", "frontend"]
    assert work_item.state == CanonicalState.DONE
    assert work_item.touch_count == 1
    assert len(work_item.state_history) == 1
    assert work_item.state_history[0].from_state == CanonicalState.IN_PROGRESS
    assert work_item.state_history[0].to_state == CanonicalState.DONE
    assert work_item.started_at == work_item.created_at
    assert work_item.completed_at is not None
    assert work_item.field_confidence["state"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["state_history"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["touch_count"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["started_at"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["completed_at"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["assignee"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["sprint_id"] == ConfidenceLevel.INFERRED


def test_github_state_map_open_and_closed():
    assert GITHUB_STATE_MAP["open"] == CanonicalState.IN_PROGRESS
    assert GITHUB_STATE_MAP["closed"] == CanonicalState.DONE

    open_item = github_issue_to_work_item(
        {**GITHUB_MINIMAL_SAMPLE, "state": "open"},
        events=[],
    )
    closed_item = github_issue_to_work_item(
        {**GITHUB_MINIMAL_SAMPLE, "state": "closed"},
        events=[],
    )

    assert open_item.state == CanonicalState.IN_PROGRESS
    assert closed_item.state == CanonicalState.DONE


def test_github_pull_request_filtering():
    pull_request = {
        **GITHUB_MINIMAL_SAMPLE,
        "pull_request": {"url": "https://api.github.com/repos/meridian/engineering/pulls/25"},
    }

    assert is_github_issue(GITHUB_MINIMAL_SAMPLE) is True
    assert is_github_issue(pull_request) is False


def test_github_graceful_degradation():
    issue = {
        "number": 42,
        "title": "Untriaged issue",
        "state": "open",
        "created_at": "2026-06-01T12:00:00Z",
        "html_url": "https://github.com/meridian/engineering/issues/42",
    }

    work_item = github_issue_to_work_item(issue, events=[])

    assert work_item.labels == []
    assert work_item.assignee is None
    assert work_item.sprint_id is None
    assert work_item.priority is None
    assert work_item.parent_id is None
    assert work_item.state_history == []
    assert work_item.touch_count == 0
    assert "assignee" not in work_item.field_confidence
    assert "sprint_id" not in work_item.field_confidence


def test_github_field_confidence_populated():
    work_item = github_issue_to_work_item(GITHUB_FULL_SAMPLE, GITHUB_FULL_SAMPLE_EVENTS)

    expected_fields = {
        "state",
        "state_history",
        "touch_count",
        "age_in_state_days",
        "started_at",
        "completed_at",
        "assignee",
        "sprint_id",
    }
    assert set(work_item.field_confidence.keys()) == expected_fields
    assert all(
        isinstance(level, ConfidenceLevel)
        for level in work_item.field_confidence.values()
    )


def test_bitbucket_issue_to_work_item_minimal():
    work_item = bitbucket_issue_to_work_item(BITBUCKET_MINIMAL_SAMPLE, changes=[])

    assert work_item.id == "25"
    assert work_item.source_system == "bitbucket"
    assert work_item.item_type == "bug"
    assert work_item.title == BITBUCKET_MINIMAL_SAMPLE["title"]
    assert work_item.labels == []
    assert work_item.state == CanonicalState.IN_PROGRESS
    assert work_item.assignee is None
    assert work_item.sprint_id is None
    assert work_item.parent_id is None
    assert work_item.priority is None
    assert work_item.state_history == []
    assert work_item.touch_count == 0
    assert work_item.started_at == work_item.created_at
    assert work_item.completed_at is None
    assert work_item.field_confidence["state"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["state_history"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["touch_count"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["started_at"] == ConfidenceLevel.INFERRED
    assert "assignee" not in work_item.field_confidence
    assert "sprint_id" not in work_item.field_confidence


def test_bitbucket_issue_to_work_item_full():
    work_item = bitbucket_issue_to_work_item(
        BITBUCKET_FULL_SAMPLE, BITBUCKET_FULL_SAMPLE_CHANGES
    )

    assert work_item.id == "25"
    assert work_item.source_system == "bitbucket"
    assert work_item.assignee == "Jim Martin"
    assert work_item.sprint_id == "Sprint 2"
    assert work_item.labels == ["frontend", "major"]
    assert work_item.state == CanonicalState.DONE
    assert work_item.touch_count == 1
    assert len(work_item.state_history) == 1
    assert work_item.state_history[0].from_state == CanonicalState.IN_PROGRESS
    assert work_item.state_history[0].to_state == CanonicalState.DONE
    assert work_item.started_at == work_item.created_at
    assert work_item.completed_at is not None
    assert work_item.field_confidence["state"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["state_history"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["touch_count"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["started_at"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["completed_at"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["assignee"] == ConfidenceLevel.EXPLICIT
    assert work_item.field_confidence["sprint_id"] == ConfidenceLevel.INFERRED
    assert work_item.field_confidence["labels"] == ConfidenceLevel.INFERRED


def test_bitbucket_state_map():
    assert BITBUCKET_STATE_MAP["new"] == CanonicalState.IN_PROGRESS
    assert BITBUCKET_STATE_MAP["open"] == CanonicalState.IN_PROGRESS
    assert BITBUCKET_STATE_MAP["resolved"] == CanonicalState.DONE
    assert BITBUCKET_STATE_MAP["closed"] == CanonicalState.DONE
    assert BITBUCKET_STATE_MAP["wontfix"] == CanonicalState.DONE

    for raw_state, expected in [
        ("new", CanonicalState.IN_PROGRESS),
        ("open", CanonicalState.IN_PROGRESS),
        ("resolved", CanonicalState.DONE),
        ("closed", CanonicalState.DONE),
        ("wontfix", CanonicalState.DONE),
    ]:
        item = bitbucket_issue_to_work_item(
            {**BITBUCKET_MINIMAL_SAMPLE, "state": raw_state},
            changes=[],
        )
        assert item.state == expected


def test_bitbucket_graceful_degradation():
    issue = {
        "id": 42,
        "title": "Untriaged issue",
        "state": "new",
        "created_on": "2026-06-01T12:00:00Z",
        "links": {"html": {"href": "https://bitbucket.org/meridian/engineering/issues/42"}},
    }

    work_item = bitbucket_issue_to_work_item(issue, changes=[])

    assert work_item.labels == []
    assert work_item.assignee is None
    assert work_item.sprint_id is None
    assert work_item.priority is None
    assert work_item.parent_id is None
    assert work_item.state_history == []
    assert work_item.touch_count == 0
    assert "assignee" not in work_item.field_confidence
    assert "sprint_id" not in work_item.field_confidence


def test_bitbucket_issues_disabled_returns_empty():
    from clearline.connectors.bitbucket_connector import fetch_bitbucket_work_items
    from clearline.connectors.fetch import SourceConnection

    connection = SourceConnection(
        source_system="bitbucket",
        base_url="https://api.bitbucket.org/2.0",
        api_token="test-token",
        project_key="workspace/repo",
    )

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.json.return_value = {"type": "error", "error": {"message": "not found"}}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "clearline.connectors.bitbucket_connector.httpx.Client",
        return_value=mock_client,
    ):
        work_items = fetch_bitbucket_work_items(connection)

    assert work_items == []


def test_bitbucket_field_confidence_populated():
    work_item = bitbucket_issue_to_work_item(
        BITBUCKET_FULL_SAMPLE, BITBUCKET_FULL_SAMPLE_CHANGES
    )

    expected_fields = {
        "state",
        "state_history",
        "touch_count",
        "age_in_state_days",
        "started_at",
        "completed_at",
        "assignee",
        "sprint_id",
        "labels",
    }
    assert set(work_item.field_confidence.keys()) == expected_fields
    assert all(
        isinstance(level, ConfidenceLevel)
        for level in work_item.field_confidence.values()
    )


def test_json_schema_export(tmp_path):
    """Schema export produces valid JSON files for all six models."""
    from clearline.ontology.v1.export import export_schemas

    export_schemas(out_dir=tmp_path)

    expected_files = [
        "work_item.json",
        "state_transition.json",
        "field_mapping.json",
        "mapping_set.json",
        "diagnostic_reliability.json",
        "failure_mode_diagnostic.json",
    ]
    for filename in expected_files:
        path = tmp_path / filename
        assert path.exists(), f"Missing schema file: {filename}"
        schema = json.loads(path.read_text())
        assert "x-ontology-version" in schema
        assert "x-generated-at" in schema
        assert schema["x-ontology-version"] == "clearline-ontology-v1.0"
