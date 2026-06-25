"""
GitHub Issues connector for Clearline ontology v1.

Fetches issues and timeline events from the GitHub REST API,
then transforms them into canonical WorkItems.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

from clearline.adapters.github_issues import (
    UNMAPPED_STATUSES,
    github_issue_to_work_item,
    is_github_issue,
)
from clearline.connectors.fetch import SourceConnection
from clearline.ontology.v1.core import WorkItem

PER_PAGE = 100
GITHUB_API_VERSION = "2022-11-28"


def _github_headers(connection: SourceConnection) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {connection.api_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


def _window_start(connection: SourceConnection) -> str:
    start = datetime.now(timezone.utc) - timedelta(days=connection.analysis_window_days)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def _api_base(connection: SourceConnection) -> str:
    return connection.base_url.rstrip("/")


def _next_path(link_header: str | None) -> str | None:
    if not link_header:
        return None

    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        url = section.split(";")[0].strip().strip("<>")
        parsed = urlparse(url)
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")

    return None


def _fetch_issues(client: httpx.Client, connection: SourceConnection) -> list[dict]:
    owner, repo = connection.project_key.split("/", 1)
    issues: list[dict] = []
    path = f"/repos/{owner}/{repo}/issues"
    params: dict[str, str | int] | None = {
        "state": "all",
        "per_page": PER_PAGE,
        "since": _window_start(connection),
    }

    while path:
        response = client.get(path, params=params)
        response.raise_for_status()
        page_issues = response.json()
        if not page_issues:
            break

        issues.extend(issue for issue in page_issues if is_github_issue(issue))

        path = _next_path(response.headers.get("Link"))
        params = None

    return issues


def _fetch_issue_events(
    client: httpx.Client, connection: SourceConnection, number: int
) -> list[dict]:
    owner, repo = connection.project_key.split("/", 1)
    events: list[dict] = []
    path = f"/repos/{owner}/{repo}/issues/{number}/events"
    params: dict[str, int] | None = {"per_page": PER_PAGE}

    while path:
        response = client.get(path, params=params)
        response.raise_for_status()
        page_events = response.json()
        if not page_events:
            break

        events.extend(page_events)

        path = _next_path(response.headers.get("Link"))
        params = None

    return events


def fetch_github_issues_work_items(connection: SourceConnection) -> list[WorkItem]:
    UNMAPPED_STATUSES.clear()

    with httpx.Client(
        base_url=_api_base(connection),
        headers=_github_headers(connection),
        timeout=60.0,
    ) as client:
        issues = _fetch_issues(client, connection)
        work_items: list[WorkItem] = []

        for issue in issues:
            events = _fetch_issue_events(client, connection, issue["number"])
            work_items.append(github_issue_to_work_item(issue, events))

    return work_items
