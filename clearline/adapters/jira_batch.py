"""
Batch Jira fetch and parity report for the Meridian (MRDN) project.

Pulls all issues with changelog expanded, transforms to WorkItems,
and writes a parity report to reports/meridian_parity.json.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from clearline.adapters.jira import (
    UNMAPPED_STATUSES,
    UNSUPPORTED_CHANGELOG_FIELDS,
    jira_issue_to_work_item,
)
from clearline.parity import generate_parity_report

JIRA_BASE_URL = "https://imuasystems.atlassian.net"
SEARCH_PATH = "/rest/api/3/search/jql"
JQL = "project=MRDN ORDER BY created ASC"
FIELDS = [
    "summary",
    "issuetype",
    "status",
    "priority",
    "assignee",
    "created",
    "updated",
    "labels",
    "parent",
    "customfield_10020",
    "resolutiondate",
]
MAX_RESULTS = 50
REPORT_PATH = Path("reports/meridian_parity.json")


def _get_credentials() -> tuple[str, str]:
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not email or not token:
        print(
            "Error: JIRA_EMAIL and JIRA_API_TOKEN must be set "
            "(via environment or .env file).",
            file=sys.stderr,
        )
        sys.exit(1)
    return email, token


def fetch_meridian_issues(client: httpx.Client) -> list[dict]:
    issues: list[dict] = []
    next_page_token: str | None = None

    while True:
        body: dict = {
            "jql": JQL,
            "expand": "changelog",
            "fields": FIELDS,
            "maxResults": MAX_RESULTS,
        }
        if next_page_token:
            body["nextPageToken"] = next_page_token

        response = client.post(SEARCH_PATH, json=body)
        response.raise_for_status()
        data = response.json()

        page = data.get("issues", [])
        issues.extend(page)

        if data.get("isLast", True) or not page:
            break
        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break

    return issues


def _field_line(name: str, coverage: dict) -> str:
    return (
        f"  {name + ':':13} "
        f"explicit={coverage.get('explicit', 0)} "
        f"inferred={coverage.get('inferred', 0)} "
        f"missing={coverage.get('missing', 0)}"
    )


def print_summary(report: dict) -> None:
    field_coverage = report["field_coverage"]
    touch = report["touch_count_distribution"]
    age = report["age_in_state_distribution"]
    adapter_meta = report.get("adapter_meta") or {}

    fidelity_pct = round(report["transition_fidelity"] * 100, 1)

    unsupported = adapter_meta.get("unsupported_changelog_fields", [])
    unmapped = adapter_meta.get("unmapped_statuses", [])

    lines = [
        "Meridian Parity Report",
        "======================",
        f"Total items:         {report['total_items']}",
        f"Transition fidelity: {fidelity_pct}%",
        f"Items with no history: {report['items_with_no_history']}",
        "",
        "Field Coverage:",
        _field_line("state", field_coverage.get("state", {})),
        _field_line("assignee", field_coverage.get("assignee", {})),
        _field_line("priority", field_coverage.get("priority", {})),
        _field_line("sprint_id", field_coverage.get("sprint_id", {})),
        _field_line("is_blocked", field_coverage.get("is_blocked", {})),
        _field_line("touch_count", field_coverage.get("touch_count", {})),
        _field_line("state_history", field_coverage.get("state_history", {})),
        "",
        f"Touch Count:  min={touch['min']:.0f} max={touch['max']:.0f} "
        f"mean={touch['mean']:.1f} median={touch['median']:.1f}",
        f"Age in State: min={age['min']:.0f} max={age['max']:.0f} "
        f"mean={age['mean']:.1f} (days)",
        "",
        f"Unsupported changelog fields: {', '.join(unsupported) or 'none'}",
        f"Unmapped Jira statuses: {', '.join(unmapped) or 'none'}",
        "",
        f"Report written to: {REPORT_PATH}",
    ]
    print("\n".join(lines))


def main() -> None:
    load_dotenv()

    UNMAPPED_STATUSES.clear()
    UNSUPPORTED_CHANGELOG_FIELDS.clear()

    email, token = _get_credentials()

    with httpx.Client(
        base_url=JIRA_BASE_URL,
        auth=(email, token),
        timeout=60.0,
    ) as client:
        issues = fetch_meridian_issues(client)

    work_items = [jira_issue_to_work_item(issue) for issue in issues]

    adapter_meta = {
        "unmapped_statuses": sorted(UNMAPPED_STATUSES),
        "unsupported_changelog_fields": sorted(UNSUPPORTED_CHANGELOG_FIELDS),
    }
    report = generate_parity_report(work_items, adapter_meta=adapter_meta)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print_summary(report)


if __name__ == "__main__":
    main()
