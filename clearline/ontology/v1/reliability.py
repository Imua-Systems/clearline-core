"""
Clearline Ontology v1 - Diagnostic Reliability
===============================================
Reliability is a first-class output, visually and architecturally equal
to the failure mode score itself.

Low reliability is not an error state. It is a consulting opportunity.

Every failure mode produces a tuple:
    score + reliability + evidence + assumptions + recommended next observation

This is the thing that makes Clearline not another engineering metrics tool.
Organizational diagnostics are inference, not measurement.
"""

from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ReliabilityBand(str, Enum):
    HIGH = "high"          # >= 0.80
    MODERATE = "moderate"  # >= 0.55
    LOW = "low"            # < 0.55


def reliability_band(score: float) -> ReliabilityBand:
    if score >= 0.80:
        return ReliabilityBand.HIGH
    elif score >= 0.55:
        return ReliabilityBand.MODERATE
    return ReliabilityBand.LOW


# ---------------------------------------------------------------------------
# Diagnostic narrative
# ---------------------------------------------------------------------------

class Signal(BaseModel):
    """Structured observation supporting a failure-mode diagnostic."""

    type: str
    description: str
    severity: Literal["low", "medium", "high"]
    affected_items: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """Human-readable diagnostic interpretation with confidence metadata."""

    summary: str
    detail: str
    confidence: Literal["High", "Medium", "Low"]
    confidence_reason: str


class DiagnosticReliability(BaseModel):
    """
    Measures the quality of Clearline's own observations.
    Composed into every failure mode output.
    """
    # Component scores (0.0 - 1.0)
    data_coverage: float = Field(ge=0.0, le=1.0)
    # What fraction of canonical fields are populated

    transition_fidelity: float = Field(ge=0.0, le=1.0)
    # How complete is the state transition history

    mapping_confidence: float = Field(ge=0.0, le=1.0)
    # Weighted avg confidence of validated field mappings

    temporal_completeness: float = Field(ge=0.0, le=1.0)
    # Coverage of timestamps needed for cycle time / age calculations

    cross_system_consistency: float = Field(ge=0.0, le=1.0)
    # Agreement across data sources when multiple systems are connected

    human_validation_coverage: float = Field(ge=0.0, le=1.0)
    # Fraction of mappings that are validated or canonical (not just proposed)

    # Composite
    reliability_score: float = Field(ge=0.0, le=1.0)
    reliability_band: ReliabilityBand

    # Narrative
    limiting_factors: list[str] = Field(default_factory=list)
    # Human-readable explanation of what's constraining reliability

    improvement_actions: list[str] = Field(default_factory=list)
    # Specific steps to improve reliability score

    @classmethod
    def compute(
        cls,
        data_coverage: float,
        transition_fidelity: float,
        mapping_confidence: float,
        temporal_completeness: float,
        cross_system_consistency: float,
        human_validation_coverage: float,
        limiting_factors: list[str] = None,
        improvement_actions: list[str] = None,
    ) -> "DiagnosticReliability":
        # Weighted composite -- transition fidelity and mapping confidence
        # carry more weight because they most directly affect score accuracy
        weights = {
            "data_coverage": 0.15,
            "transition_fidelity": 0.25,
            "mapping_confidence": 0.25,
            "temporal_completeness": 0.15,
            "cross_system_consistency": 0.10,
            "human_validation_coverage": 0.10,
        }
        score = (
            data_coverage * weights["data_coverage"]
            + transition_fidelity * weights["transition_fidelity"]
            + mapping_confidence * weights["mapping_confidence"]
            + temporal_completeness * weights["temporal_completeness"]
            + cross_system_consistency * weights["cross_system_consistency"]
            + human_validation_coverage * weights["human_validation_coverage"]
        )
        return cls(
            data_coverage=data_coverage,
            transition_fidelity=transition_fidelity,
            mapping_confidence=mapping_confidence,
            temporal_completeness=temporal_completeness,
            cross_system_consistency=cross_system_consistency,
            human_validation_coverage=human_validation_coverage,
            reliability_score=round(score, 3),
            reliability_band=reliability_band(score),
            limiting_factors=limiting_factors or [],
            improvement_actions=improvement_actions or [],
        )


# ---------------------------------------------------------------------------
# Failure Mode Tuple
# ---------------------------------------------------------------------------

class FailureModeDiagnostic(BaseModel):
    """
    The core output artifact of Clearline.
    Score and reliability are visually and architecturally equal.
    The report does not say 'trust us.' It says 'here is our reasoning.'
    """
    failure_mode: str          # e.g. "Leadership Entropy"
    score: float               # 0 - 100
    band: str                  # e.g. "High", "Developing", "Healthy"

    reliability: DiagnosticReliability

    evidence: list[str] = Field(default_factory=list)
    # Specific observations supporting the score
    # e.g. "High touch count", "Frequent reassignment"

    assumptions: list[str] = Field(default_factory=list)
    # What Clearline assumed where data was missing or inferred
    # e.g. "Blocked states inferred from label patterns"

    recommended_next_observation: list[str] = Field(default_factory=list)
    # What data would most improve reliability for this failure mode
    # e.g. "Connect revision history", "Validate dependency fields"

    ontology_version: str = "clearline-ontology-v1.0"
