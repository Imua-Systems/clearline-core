"""
Tool-agnostic parity validator for Clearline ontology v1.

Accepts canonical WorkItem objects and produces a structured coverage report.
Knows nothing about source systems or adapters.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict

from clearline.ontology.v1.core import (
    ONTOLOGY_VERSION,
    CanonicalState,
    ConfidenceLevel,
    WorkItem,
)


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0}
    return {
        "min": float(min(values)),
        "max": float(max(values)),
        "mean": float(statistics.mean(values)),
        "median": float(statistics.median(values)),
    }


def _confidence_counts(levels: list[ConfidenceLevel]) -> dict[str, int]:
    counts = Counter(level.value for level in levels)
    return {
        "explicit": counts.get("explicit", 0),
        "inferred": counts.get("inferred", 0),
        "missing": counts.get("missing", 0),
        "contradicted": counts.get("contradicted", 0),
    }


def generate_parity_report(
    items: list[WorkItem],
    adapter_meta: dict | None = None,
) -> dict:
    field_coverage: dict[str, dict[str, int]] = defaultdict(
        lambda: {"explicit": 0, "inferred": 0, "missing": 0, "contradicted": 0}
    )

    state_distribution = {state.value: 0 for state in CanonicalState}
    touch_counts: list[float] = []
    ages_in_state: list[float] = []
    items_with_history = 0
    report_items: list[dict] = []

    for item in items:
        for field_name, level in item.field_confidence.items():
            field_coverage[field_name][level.value] += 1

        state_distribution[item.state.value] += 1

        if item.touch_count is not None:
            touch_counts.append(float(item.touch_count))

        if item.age_in_state_days is not None:
            ages_in_state.append(float(item.age_in_state_days))

        transition_count = len(item.state_history)
        if transition_count > 0:
            items_with_history += 1

        report_items.append(
            {
                "id": item.id,
                "state": item.state.value,
                "touch_count": item.touch_count,
                "age_in_state_days": item.age_in_state_days,
                "transition_count": transition_count,
                "confidence_summary": _confidence_counts(
                    list(item.field_confidence.values())
                ),
            }
        )

    total_items = len(items)
    transition_fidelity = items_with_history / total_items if total_items else 0.0

    return {
        "ontology_version": ONTOLOGY_VERSION,
        "total_items": total_items,
        "adapter_meta": adapter_meta,
        "field_coverage": dict(field_coverage),
        "transition_fidelity": transition_fidelity,
        "items_with_no_history": total_items - items_with_history,
        "state_distribution": state_distribution,
        "touch_count_distribution": _distribution(touch_counts),
        "age_in_state_distribution": _distribution(ages_in_state),
        "items": report_items,
    }


if __name__ == "__main__":
    from clearline.adapters.jira import (
        MRDN_25_SAMPLE,
        UNMAPPED_STATUSES,
        UNSUPPORTED_CHANGELOG_FIELDS,
        jira_issue_to_work_item,
    )

    work_item = jira_issue_to_work_item(MRDN_25_SAMPLE)
    adapter_meta = {
        "unmapped_statuses": sorted(UNMAPPED_STATUSES),
        "unsupported_changelog_fields": sorted(UNSUPPORTED_CHANGELOG_FIELDS),
    }
    report = generate_parity_report([work_item], adapter_meta=adapter_meta)
    print(json.dumps(report, indent=2))
