"""
Clearline Ontology v1 - Mapping Layer
======================================
Agent-assisted, human-governed field mappings from source systems
to the canonical ontology.

Governance:
    PROPOSED    -> agent only, never affects scores
    VALIDATED   -> confirmed by client admin, may affect scores
    CANONICAL   -> promoted by Imua, reusable across clients

The agent is interpretive. The ontology is authoritative.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from .core import ConfidenceLevel, MappingStatus, ONTOLOGY_VERSION


class FieldMapping(BaseModel):
    # Source field
    source_system: str
    source_field: str
    source_field_example: Optional[str] = None  # sample value for audit/debug

    # Target in canonical ontology
    target_field: str

    # Confidence and rationale
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel
    rationale: str  # agent-generated or human-written explanation

    # Governance
    status: MappingStatus = MappingStatus.PROPOSED
    ontology_version: str = ONTOLOGY_VERSION

    # Provenance
    proposed_by: str       # "agent" or user identifier
    proposed_at: datetime
    validated_by: Optional[str] = None
    validated_at: Optional[datetime] = None
    canonicalized_by: Optional[str] = None
    canonicalized_at: Optional[datetime] = None

    # Scope
    client_id: Optional[str] = None  # None if canonical (cross-client)


class MappingSet(BaseModel):
    """
    A complete set of field mappings for a given source system and client.
    The agent proposes a MappingSet on first connection.
    Humans validate individual FieldMappings within it.
    """
    id: str
    client_id: str
    source_system: str
    ontology_version: str = ONTOLOGY_VERSION
    created_at: datetime
    mappings: list[FieldMapping] = Field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Fraction of canonical fields that have at least a proposed mapping."""
        if not self.mappings:
            return 0.0
        canonical_fields = {m.target_field for m in self.mappings}
        # Core required fields in the canonical model
        required = {
            "state", "created_at", "id", "item_type",
            "priority", "assignee", "parent_id", "sprint_id",
            "is_blocked", "state_history"
        }
        return len(canonical_fields & required) / len(required)

    @property
    def validation_coverage(self) -> float:
        """Fraction of mappings that have been human-validated or canonical."""
        if not self.mappings:
            return 0.0
        validated = [
            m for m in self.mappings
            if m.status in (MappingStatus.VALIDATED, MappingStatus.CANONICAL)
        ]
        return len(validated) / len(self.mappings)
