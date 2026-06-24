"""
Validate ado_work_item_to_work_item against live ADO Meridian Engineering project.
Prints a summary of field coverage and any unmapped states or errors.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

from clearline.adapters.ado import (
    UNMAPPED_STATUSES,
    ado_work_item_to_work_item,
)
from clearline.ontology.v1.core import ConfidenceLevel, WorkItem

load_dotenv()

ORG = "imuasystems"
PROJECT = "Meridian Engineering"
PAT = os.environ.get("ADO_PAT")

API_VERSION = "7.1"
BATCH_SIZE = 20
WIQL = f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{PROJECT}'"

TRACKED_FIELDS = (
    "state",
    "state_history",
    "touch_count",
    "age_in_state_days",
    "started_at",
    "assignee",
    "priority",
    "parent_id",
)


def _org_base() -> str:
    return f"https://dev.azure.com/{ORG}/_apis"


def _project_base() -> str:
    return f"https://dev.azure.com/{ORG}/{quote(PROJECT)}/_apis"


def _require_pat() -> str:
    if not PAT:
        print(
            "Error: ADO_PAT must be set (via environment or .env file).",
            file=sys.stderr,
        )
        sys.exit(1)
    return PAT


def fetch_work_item_ids(client: httpx.Client) -> list[int]:
    response = client.post(
        f"{_project_base()}/wit/wiql",
        params={"api-version": API_VERSION},
        json={"query": WIQL},
    )
    response.raise_for_status()
    work_items = response.json().get("workItems", [])
    return [item["id"] for item in work_items]


def fetch_work_items(client: httpx.Client, ids: list[int]) -> list[dict]:
    items: list[dict] = []
    for offset in range(0, len(ids), BATCH_SIZE):
        batch = ids[offset : offset + BATCH_SIZE]
        response = client.get(
            f"{_org_base()}/wit/workitems",
            params={
                "ids": ",".join(str(item_id) for item_id in batch),
                "$expand": "all",
                "api-version": API_VERSION,
            },
        )
        response.raise_for_status()
        items.extend(response.json().get("value", []))
    return items


def fetch_revisions(client: httpx.Client, item_id: int) -> list[dict]:
    response = client.get(
        f"{_org_base()}/wit/workitems/{item_id}/revisions",
        params={"api-version": API_VERSION},
    )
    response.raise_for_status()
    return response.json().get("value", [])


def _confidence_counts(items: list[WorkItem]) -> dict[str, dict[str, int]]:
    coverage: dict[str, dict[str, int]] = {
        field: {"explicit": 0, "inferred": 0, "missing": 0, "contradicted": 0}
        for field in TRACKED_FIELDS
    }

    for item in items:
        for field in TRACKED_FIELDS:
            level = item.field_confidence.get(field, ConfidenceLevel.MISSING)
            coverage[field][level.value] += 1

    return coverage


def _field_line(name: str, coverage: dict[str, int]) -> str:
    return (
        f"  {name + ':':16} "
        f"explicit={coverage.get('explicit', 0)} "
        f"inferred={coverage.get('inferred', 0)} "
        f"missing={coverage.get('missing', 0)}"
    )


def _print_table(rows: list[dict]) -> None:
    headers = ("ID", "type", "state", "touch", "parent", "assignee", "priority_conf")
    widths = [6, 14, 14, 6, 8, 20, 14]

    def fmt_row(values: tuple[str, ...]) -> str:
        return "  ".join(value.ljust(width) for value, width in zip(values, widths))

    print(fmt_row(headers))
    print(fmt_row(tuple("-" * (width - 1) for width in widths)))
    for row in rows:
        print(
            fmt_row(
                (
                    row["id"],
                    row["item_type"],
                    row["state"],
                    row["touch_count"],
                    row["parent_id"],
                    row["assignee"],
                    row["priority_conf"],
                )
            )
        )


def main() -> None:
    UNMAPPED_STATUSES.clear()

    pat = _require_pat()

    errors: list[str] = []
    work_items: list[WorkItem] = []
    table_rows: list[dict] = []

    with httpx.Client(auth=("", pat), timeout=60.0) as client:
        item_ids = fetch_work_item_ids(client)
        print(f"Found {len(item_ids)} work items in {PROJECT}")

        raw_items = fetch_work_items(client, item_ids)
        raw_by_id = {item["id"]: item for item in raw_items}

        for item_id in item_ids:
            item = raw_by_id.get(item_id)
            if item is None:
                errors.append(f"{item_id}: work item not returned by batch fetch")
                continue

            try:
                revisions = fetch_revisions(client, item_id)
                work_item = ado_work_item_to_work_item(item, revisions)
                work_items.append(work_item)

                priority_conf = work_item.field_confidence.get(
                    "priority", ConfidenceLevel.MISSING
                )
                table_rows.append(
                    {
                        "id": work_item.id,
                        "item_type": work_item.item_type or "",
                        "state": work_item.state.value,
                        "touch_count": (
                            str(work_item.touch_count)
                            if work_item.touch_count is not None
                            else ""
                        ),
                        "parent_id": work_item.parent_id or "",
                        "assignee": work_item.assignee or "",
                        "priority_conf": priority_conf.value,
                    }
                )
            except Exception as exc:
                errors.append(f"{item_id}: {exc}")

    print()
    _print_table(table_rows)

    coverage = _confidence_counts(work_items)

    print()
    print("Summary")
    print("=======")
    print(f"Total items:  {len(item_ids)}")
    print(f"Transformed:  {len(work_items)}")
    print(f"Total errors: {len(errors)}")
    print()
    print("Field coverage:")
    for field in TRACKED_FIELDS:
        print(_field_line(field, coverage[field]))

    if errors:
        print()
        print("Errors:")
        for error in errors:
            print(f"  {error}")

    print()
    print(
        "Unmapped ADO states: "
        + (", ".join(sorted(UNMAPPED_STATUSES)) or "none")
    )


if __name__ == "__main__":
    main()
