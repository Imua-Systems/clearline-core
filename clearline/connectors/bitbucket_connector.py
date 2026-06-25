"""
Bitbucket connector for Clearline ontology v1.

Fetches issues and issue changes from the Bitbucket REST API,
then transforms them into canonical WorkItems.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from clearline.adapters.bitbucket import UNMAPPED_STATUSES, bitbucket_issue_to_work_item
from clearline.connectors.fetch import SourceConnection
from clearline.ontology.v1.core import WorkItem

logger = logging.getLogger(__name__)

PAGE_LEN = 50


def _split_project_key(project_key: str) -> tuple[str, str]:
    workspace, repo_slug = project_key.split("/", 1)
    return workspace, repo_slug


def _window_start(connection: SourceConnection) -> str:
    start = datetime.now(timezone.utc) - timedelta(days=connection.analysis_window_days)
    return start.strftime("%Y-%m-%dT%H:%M:%S")


def _api_base(connection: SourceConnection) -> str:
    return connection.base_url.rstrip("/")


def _issues_unavailable(response: httpx.Response) -> bool:
    if response.status_code == 404:
        return True

    try:
        body = response.json()
    except Exception:
        return False

    return body.get("type") == "error"


def _fetch_issues(client: httpx.Client, connection: SourceConnection) -> list[dict]:
    workspace, repo_slug = _split_project_key(connection.project_key)
    issues: list[dict] = []
    path = f"/repositories/{workspace}/{repo_slug}/issues"
    params: dict[str, str | int] | None = {
        "q": f"updated_on>={_window_start(connection)}",
        "pagelen": PAGE_LEN,
    }

    while path:
        response = client.get(path, params=params)
        if _issues_unavailable(response):
            logger.warning(
                "Bitbucket issues not enabled for repository %s",
                connection.project_key,
            )
            return []

        response.raise_for_status()
        data = response.json()

        if data.get("type") == "error":
            logger.warning(
                "Bitbucket issues API returned error for repository %s: %s",
                connection.project_key,
                data.get("error", {}).get("message", "unknown error"),
            )
            return []

        issues.extend(data.get("values", []))

        next_url = data.get("next")
        if not next_url:
            break

        path = next_url
        params = None

    return issues


def _fetch_issue_changes(
    client: httpx.Client, connection: SourceConnection, issue_id: int
) -> list[dict]:
    workspace, repo_slug = _split_project_key(connection.project_key)
    changes: list[dict] = []
    path = f"/repositories/{workspace}/{repo_slug}/issues/{issue_id}/changes"
    params: dict[str, int] | None = {"pagelen": PAGE_LEN}

    while path:
        response = client.get(path, params=params)
        response.raise_for_status()
        data = response.json()
        changes.extend(data.get("values", []))

        next_url = data.get("next")
        if not next_url:
            break

        path = next_url
        params = None

    return changes


def fetch_bitbucket_work_items(connection: SourceConnection) -> list[WorkItem]:
    UNMAPPED_STATUSES.clear()

    headers = {"Authorization": f"Bearer {connection.api_token}"}

    with httpx.Client(
        base_url=_api_base(connection),
        headers=headers,
        timeout=60.0,
    ) as client:
        issues = _fetch_issues(client, connection)
        work_items: list[WorkItem] = []

        for issue in issues:
            changes = _fetch_issue_changes(client, connection, issue["id"])
            work_items.append(bitbucket_issue_to_work_item(issue, changes))

    return work_items
