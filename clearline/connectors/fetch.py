"""
Source connection model and work-item fetch dispatch for Clearline connectors.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from clearline.ontology.v1.core import WorkItem


class SourceConnection(BaseModel):
    source_system: str
    base_url: str = "https://gitlab.com"
    api_token: str
    project_key: str
    analysis_window_days: int = Field(default=90, ge=1)


def fetch_work_items(connection: SourceConnection) -> list[WorkItem]:
    if connection.source_system == "gitlab":
        from clearline.connectors.gitlab_connector import fetch_gitlab_work_items

        return fetch_gitlab_work_items(connection)

    if connection.source_system == "github_issues":
        from clearline.connectors.github_issues_connector import (
            fetch_github_issues_work_items,
        )

        return fetch_github_issues_work_items(connection)

    raise ValueError(f"Unsupported source system: {connection.source_system}")
