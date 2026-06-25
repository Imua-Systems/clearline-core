"""
GitLab connector for Clearline ontology v1.

Fetches issues and resource state events from the GitLab REST API,
then transforms them into canonical WorkItems.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from clearline.adapters.gitlab import UNMAPPED_STATUSES, gitlab_issue_to_work_item
from clearline.connectors.fetch import SourceConnection
from clearline.ontology.v1.core import WorkItem

PER_PAGE = 100


def _encoded_project_key(project_key: str) -> str:
    return quote(project_key, safe="")


def _window_start(connection: SourceConnection) -> str:
    start = datetime.now(timezone.utc) - timedelta(days=connection.analysis_window_days)
    return start.isoformat()


def _api_base(connection: SourceConnection) -> str:
    return connection.base_url.rstrip("/") + "/api/v4"


def _fetch_issues(client: httpx.Client, connection: SourceConnection) -> list[dict]:
    project = _encoded_project_key(connection.project_key)
    issues: list[dict] = []
    page = 1

    while True:
        response = client.get(
            f"/projects/{project}/issues",
            params={
                "per_page": PER_PAGE,
                "page": page,
                "updated_after": _window_start(connection),
            },
        )
        response.raise_for_status()
        page_issues = response.json()
        if not page_issues:
            break

        issues.extend(page_issues)

        next_page = response.headers.get("X-Next-Page")
        if not next_page:
            break
        page = int(next_page)

    return issues


def _fetch_state_events(
    client: httpx.Client, connection: SourceConnection, iid: int
) -> list[dict]:
    project = _encoded_project_key(connection.project_key)
    response = client.get(
        f"/projects/{project}/issues/{iid}/resource_state_events",
        params={"per_page": PER_PAGE},
    )
    response.raise_for_status()
    return response.json()


def fetch_gitlab_work_items(connection: SourceConnection) -> list[WorkItem]:
    UNMAPPED_STATUSES.clear()

    headers = {"PRIVATE-TOKEN": connection.api_token}

    with httpx.Client(base_url=_api_base(connection), headers=headers, timeout=60.0) as client:
        issues = _fetch_issues(client, connection)
        work_items: list[WorkItem] = []

        for issue in issues:
            events = _fetch_state_events(client, connection, issue["iid"])
            work_items.append(gitlab_issue_to_work_item(issue, events))

    return work_items
