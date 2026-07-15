"""
Clearline Ontology v1 — JSON Schema Export

Python/Pydantic is the source of truth.
JSON Schema is the contract for API and UI consumers.
TypeScript types should be generated from these schemas, not written by hand.

Run:
    python -m clearline.ontology.v1.export
    python -m clearline.ontology.v1.export --out-dir path/to/output

Output: one .json file per model in clearline/ontology/v1/schema/
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from clearline.ontology.v1.core import (
    ONTOLOGY_VERSION,
    ClosedSprintRef,
    EstimateTransition,
    PriorityTransition,
    Sprint,
    SprintContext,
    SprintTransition,
    StateTransition,
    WorkItem,
)
from clearline.ontology.v1.mapping import FieldMapping, MappingSet
from clearline.ontology.v1.reliability import DiagnosticReliability, FailureModeDiagnostic, Finding, Signal

DEFAULT_SCHEMA_DIR = Path(__file__).parent / "schema"
DEFAULT_DISPLAY_DIR = "clearline/ontology/v1/schema/"

SCHEMA_EXPORTS: list[tuple[type, str]] = [
    (WorkItem, "work_item.json"),
    (StateTransition, "state_transition.json"),
    (PriorityTransition, "priority_transition.json"),
    (EstimateTransition, "estimate_transition.json"),
    (SprintTransition, "sprint_transition.json"),
    (Sprint, "sprint.json"),
    (ClosedSprintRef, "closed_sprint_ref.json"),
    (SprintContext, "sprint_context.json"),
    (FieldMapping, "field_mapping.json"),
    (MappingSet, "mapping_set.json"),
    (DiagnosticReliability, "diagnostic_reliability.json"),
    (FailureModeDiagnostic, "failure_mode_diagnostic.json"),
    (Signal, "signal.json"),
    (Finding, "finding.json"),
]


def export_schemas(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    for model, filename in SCHEMA_EXPORTS:
        schema = model.model_json_schema()
        schema["x-ontology-version"] = ONTOLOGY_VERSION
        schema["x-generated-at"] = datetime.utcnow().isoformat() + "Z"

        path = out_dir / filename
        path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        print(f"  wrote: schema/{filename}")

    return len(SCHEMA_EXPORTS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Clearline ontology v1 JSON schemas")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_SCHEMA_DIR,
        help="Output directory for schema JSON files",
    )
    args = parser.parse_args()

    count = export_schemas(args.out_dir)
    display_dir = DEFAULT_DISPLAY_DIR if args.out_dir == DEFAULT_SCHEMA_DIR else args.out_dir
    print(f"Exported {count} schemas to {display_dir}")


if __name__ == "__main__":
    main()
