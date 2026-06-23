from datetime import datetime, timezone
import json

import pytest

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
