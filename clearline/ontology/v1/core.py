"""
Clearline Ontology v1 - Core
============================
This is the spine of Clearline. It is code-owned, versioned, and deterministic.
Agents may interpret it. Clients may extend it via the mapping layer.
Nothing mutates it without an explicit version bump.
"""

from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


ONTOLOGY_VERSION = "clearline-ontology-v1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CanonicalState(str, Enum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"        # structural: upstream dependency, queue
    BLOCKED = "blocked"        # active: identified impediment
    REVIEW = "review"
    DONE = "done"
    ABANDONED = "abandoned"


class ConfidenceLevel(str, Enum):
    EXPLICIT = "explicit"        # field present and unambiguous in source
    INFERRED = "inferred"        # derived from related fields or patterns
    MISSING = "missing"          # field absent from source system
    CONTRADICTED = "contradicted"  # conflicting signals in source data


class MappingStatus(str, Enum):
    PROPOSED = "proposed"      # agent-generated, never affects scores
    VALIDATED = "validated"    # confirmed by client human, may affect scores
    CANONICAL = "canonical"    # promoted by Imua, reusable across clients


class PriorityChangeKind(str, Enum):
    """Distinguishes the kind of prioritization signal in a PriorityTransition.

    Backlog reprioritization surfaces in source systems in two distinct ways.
    Keeping them separate lets detector logic reason about explicit priority
    field changes independently from rank/order (drag-and-drop) movement.
    """
    PRIORITY = "priority"  # explicit priority field change (e.g. Medium -> High)
    RANK = "rank"          # backlog rank/order movement (e.g. Jira "Rank")


# ---------------------------------------------------------------------------
# State Transition (for history tracking)
# ---------------------------------------------------------------------------

class StateTransition(BaseModel):
    from_state: Optional[CanonicalState] = None
    to_state: CanonicalState
    transitioned_at: datetime
    transitioned_by: Optional[str] = None
    source_status: Optional[str] = None  # raw status label from source system


class SprintTransition(BaseModel):
    from_sprint: Optional[str] = None  # Jira fromString sprint name/label
    to_sprint: Optional[str] = None  # Jira toString sprint name/label
    transitioned_at: datetime
    transitioned_by: Optional[str] = None


class PriorityTransition(BaseModel):
    from_priority: Optional[str] = None  # source fromString label (priority or rank)
    to_priority: Optional[str] = None  # source toString label (priority or rank)
    transitioned_at: datetime
    transitioned_by: Optional[str] = None
    # Canonical kind of prioritization signal. Defaults to PRIORITY so existing
    # priority-field transitions are unchanged for consumers that ignore it.
    change_kind: PriorityChangeKind = PriorityChangeKind.PRIORITY
    # Raw source field name that produced this transition (e.g. "priority",
    # "Rank"). Preserved so detectors can trace back to the origin field.
    source_field: Optional[str] = None


class EstimateTransition(BaseModel):
    """Timestamped story-point / estimate change from source changelog."""

    from_value: Optional[float] = None
    to_value: Optional[float] = None
    transitioned_at: datetime
    transitioned_by: Optional[str] = None
    # Raw source field name (e.g. "Story Points") or id when name is absent.
    source_field: Optional[str] = None


# ---------------------------------------------------------------------------
# Canonical Work Item
# ---------------------------------------------------------------------------

class WorkItem(BaseModel):
    # Identity
    id: str
    source_system: str
    source_url: Optional[str] = None
    ontology_version: str = ONTOLOGY_VERSION

    # Descriptive
    item_type: Optional[str] = None
    title: Optional[str] = None
    labels: list[str] = Field(default_factory=list)

    # State
    state: CanonicalState
    state_changed_at: Optional[datetime] = None
    state_history: list[StateTransition] = Field(default_factory=list)
    sprint_history: list[SprintTransition] = Field(default_factory=list)
    priority_history: list[PriorityTransition] = Field(default_factory=list)
    estimate_history: list[EstimateTransition] = Field(default_factory=list)

    # Priority, estimate, and ownership
    priority: Optional[str] = None
    estimate: Optional[float] = None  # current story points / size estimate
    assignee: Optional[str] = None

    # Timestamps
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Hierarchy
    parent_id: Optional[str] = None
    sprint_id: Optional[str] = None

    # Impediment signals
    is_blocked: Optional[bool] = None
    blocker_reason: Optional[str] = None

    # Derived delivery metrics
    age_in_state_days: Optional[float] = None
    touch_count: Optional[int] = None  # state changes + reassignments

    # Confidence metadata: keyed by field name
    field_confidence: dict[str, ConfidenceLevel] = Field(default_factory=dict)
