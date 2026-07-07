"""Probe: confirm Rank-based reprioritization surfaces in priority history.

Fetches real Jira issues (changelog expanded) through the production adapter
path (``jira_issue_to_work_item``) and reports, per issue, the priority-history
transitions split by kind (explicit priority field changes vs. rank/order
movement).

This verifies IMUA-102: Rank / customfield_10019 changelog events are no longer
silently dropped by ``_extract_priority_history`` and are distinguishable from
explicit priority changes via ``PriorityTransition.change_kind``.

Run:
    python -m scripts.probe_rank_history
    python -m scripts.probe_rank_history --projects MRDN IMUA
    python -m scripts.probe_rank_history --issues MRDN-25 IMUA-42

Requires JIRA_EMAIL and JIRA_API_TOKEN (via environment or .env).
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx
from dotenv import load_dotenv

from clearline.adapters.jira import (
    UNSUPPORTED_CHANGELOG_FIELDS,
    jira_issue_to_work_item,
)
from clearline.ontology.v1.core import PriorityChangeKind

JIRA_BASE_URL = "https://imuasystems.atlassian.net"
SEARCH_PATH = "/rest/api/3/search/jql"
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


def _fetch(client: httpx.Client, jql: str) -> list[dict]:
    issues: list[dict] = []
    next_page_token: str | None = None

    while True:
        body: dict = {
            "jql": jql,
            "expand": "changelog",
            "fields": FIELDS,
            "maxResults": 50,
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


def _quote(keys: list[str]) -> str:
    return ", ".join(f'"{k}"' for k in keys)


def probe(issues: list[dict]) -> dict:
    issues_with_rank = 0
    issues_with_priority = 0
    issues_with_any = 0
    rank_transition_count = 0
    priority_transition_count = 0
    examples: list[dict] = []

    for issue in issues:
        work_item = jira_issue_to_work_item(issue)
        history = work_item.priority_history
        if not history:
            continue

        issues_with_any += 1
        rank = [t for t in history if t.change_kind == PriorityChangeKind.RANK]
        priority = [
            t for t in history if t.change_kind == PriorityChangeKind.PRIORITY
        ]
        rank_transition_count += len(rank)
        priority_transition_count += len(priority)
        if rank:
            issues_with_rank += 1
        if priority:
            issues_with_priority += 1

        if rank and len(examples) < 10:
            sample = rank[0]
            examples.append(
                {
                    "issue": work_item.id,
                    "change_kind": sample.change_kind.value,
                    "source_field": sample.source_field,
                    "from": sample.from_priority,
                    "to": sample.to_priority,
                    "at": sample.transitioned_at.isoformat(),
                    "by": sample.transitioned_by,
                }
            )

    return {
        "issues_scanned": len(issues),
        "issues_with_priority_history": issues_with_any,
        "issues_with_priority_field_changes": issues_with_priority,
        "issues_with_rank_movement": issues_with_rank,
        "priority_field_transition_count": priority_transition_count,
        "rank_transition_count": rank_transition_count,
        "rank_examples": examples,
    }


def _print_result(label: str, result: dict) -> None:
    print(f"=== {label} ===")
    print(f"  issues scanned:                 {result['issues_scanned']}")
    print(f"  issues w/ priority history:     {result['issues_with_priority_history']}")
    print(
        f"  issues w/ priority-field change: {result['issues_with_priority_field_changes']}"
    )
    print(f"  issues w/ RANK movement:        {result['issues_with_rank_movement']}")
    print(f"  priority-field transitions:     {result['priority_field_transition_count']}")
    print(f"  RANK transitions:               {result['rank_transition_count']}")
    if result["rank_examples"]:
        print("  RANK examples:")
        for ex in result["rank_examples"]:
            print(
                f"    {ex['issue']}: [{ex['change_kind']}/{ex['source_field']}] "
                f"{ex['from']!r} -> {ex['to']!r} @ {ex['at']} by {ex['by']}"
            )
    else:
        print("  RANK examples: none found in this set")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Rank priority history")
    parser.add_argument(
        "--projects",
        nargs="*",
        default=["MRDN", "IMUA"],
        help="Project keys to scan (ignored if --issues is given)",
    )
    parser.add_argument(
        "--issues",
        nargs="*",
        default=None,
        help="Specific issue keys to probe (e.g. MRDN-25)",
    )
    args = parser.parse_args()

    load_dotenv()
    UNSUPPORTED_CHANGELOG_FIELDS.clear()
    email, token = _get_credentials()

    total_rank = 0
    with httpx.Client(
        base_url=JIRA_BASE_URL, auth=(email, token), timeout=60.0
    ) as client:
        if args.issues:
            jql = f"key IN ({_quote(args.issues)}) ORDER BY created ASC"
            issues = _fetch(client, jql)
            result = probe(issues)
            total_rank += result["rank_transition_count"]
            _print_result("ISSUES " + ", ".join(args.issues), result)
        else:
            for project in args.projects:
                jql = f"project={project} ORDER BY created ASC"
                issues = _fetch(client, jql)
                result = probe(issues)
                total_rank += result["rank_transition_count"]
                _print_result(f"PROJECT {project}", result)

    unsupported = sorted(UNSUPPORTED_CHANGELOG_FIELDS)
    print(f"Unsupported changelog fields observed: {', '.join(unsupported) or 'none'}")
    if "Rank" in UNSUPPORTED_CHANGELOG_FIELDS:
        print("  WARNING: Rank still reported as unsupported changelog field.")
    else:
        print("  OK: Rank is not reported as an unsupported changelog field.")

    print()
    if total_rank > 0:
        print(f"RESULT: PASS - captured {total_rank} rank transition(s); "
              "Priority Movement has a direct evidence path for Rank-based "
              "reprioritization.")
    else:
        print("RESULT: No rank transitions observed in the scanned set. "
              "This is an observation, not a failure. Try --issues with a known "
              "reprioritized issue (e.g. MRDN-25).")


if __name__ == "__main__":
    main()
