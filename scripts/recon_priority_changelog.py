"""Phase 1 recon: scan Jira changelogs for priority field transitions."""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

import httpx
from dotenv import load_dotenv

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


def fetch_project(client: httpx.Client, project_key: str) -> list[dict]:
    issues: list[dict] = []
    next_page_token: str | None = None

    while True:
        body: dict = {
            "jql": f"project={project_key} ORDER BY created ASC",
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


def scan_priority_changes(issues: list[dict]) -> dict:
    samples: list[dict] = []
    issues_with_priority_change: list[str] = []
    field_variants: dict[str, int] = defaultdict(int)
    total_histories = 0
    issues_with_changelog = 0
    issues_without_changelog = 0
    priority_transition_count = 0

    for issue in issues:
        changelog = issue.get("changelog")
        if changelog is None:
            issues_without_changelog += 1
            continue

        issues_with_changelog += 1
        histories = changelog.get("histories", [])
        total_histories += len(histories)

        for history in histories:
            for item in history.get("items", []):
                field = item.get("field", "")
                field_variants[field] += 1
                if field.lower() != "priority":
                    continue

                priority_transition_count += 1
                entry = {
                    "issue_key": issue.get("key"),
                    "field": field,
                    "fromString": item.get("fromString"),
                    "toString": item.get("toString"),
                    "from": item.get("from"),
                    "to": item.get("to"),
                    "created": history.get("created"),
                    "author": history.get("author"),
                }
                if issue.get("key") not in issues_with_priority_change:
                    issues_with_priority_change.append(issue.get("key"))
                if len(samples) < 5:
                    samples.append(entry)

    return {
        "issues_sampled": len(issues),
        "issues_with_changelog": issues_with_changelog,
        "issues_without_changelog": issues_without_changelog,
        "total_histories": total_histories,
        "priority_transition_count": priority_transition_count,
        "issues_with_priority_change": issues_with_priority_change,
        "samples": samples,
        "priority_like_fields": {
            k: v for k, v in field_variants.items() if "prior" in k.lower()
        },
        "top_fields_seen": dict(
            sorted(field_variants.items(), key=lambda x: -x[1])[:20]
        ),
    }


def main() -> None:
    load_dotenv()
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not email or not token:
        print("Error: JIRA_EMAIL and JIRA_API_TOKEN must be set.", file=sys.stderr)
        sys.exit(1)

    with httpx.Client(
        base_url=JIRA_BASE_URL,
        auth=(email, token),
        timeout=60.0,
    ) as client:
        for project in ("MRDN", "IMUA"):
            print(f"=== PROJECT {project} ===")
            issues = fetch_project(client, project)
            result = scan_priority_changes(issues)
            summary = {k: v for k, v in result.items() if k != "samples"}
            print(json.dumps(summary, indent=2))
            print("SAMPLES:")
            print(json.dumps(result["samples"], indent=2, default=str))
            print()


if __name__ == "__main__":
    main()
