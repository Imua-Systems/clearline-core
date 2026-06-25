# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added

- **GitLab adapter** (`clearline/adapters/gitlab.py`) — transforms GitLab issue dicts and `resource_state_events` into canonical `WorkItem` objects; exports `GITLAB_STATE_MAP` and `gitlab_issue_to_work_item` from `clearline.ontology.v1` (IMUA-46)
- **GitLab connector** (`clearline/connectors/gitlab_connector.py`) — fetches issues and state events from the GitLab REST API via `SourceConnection`
- **GitHub Issues adapter** (`clearline/adapters/github_issues.py`) — transforms GitHub issue dicts and timeline events into canonical `WorkItem` objects with graceful degradation for optional fields; exports `GITHUB_STATE_MAP` and `github_issue_to_work_item` from `clearline.ontology.v1` (IMUA-47)
- **GitHub Issues connector** (`clearline/connectors/github_issues_connector.py`) — fetches issues (excluding pull requests) and timeline events from the GitHub REST API via `SourceConnection`
- **Bitbucket adapter** (`clearline/adapters/bitbucket.py`) — transforms Bitbucket issue dicts and issue changes into canonical `WorkItem` objects with graceful degradation for optional fields; exports `BITBUCKET_STATE_MAP` and `bitbucket_issue_to_work_item` from `clearline.ontology.v1` (IMUA-48)
- **Bitbucket connector** (`clearline/connectors/bitbucket_connector.py`) — fetches issues and issue changes from the Bitbucket REST API via `SourceConnection`; returns an empty list when issues are disabled for the repository
- **Connector dispatch** (`clearline/connectors/fetch.py`) — `SourceConnection` model and `fetch_work_items()` routing for `gitlab`, `github_issues`, and `bitbucket`
- **ADO adapter** (`clearline/adapters/ado.py`) — transforms raw Azure DevOps work item API responses (with revision history) into canonical `WorkItem` objects; exports `ADO_STATE_MAP` and `ado_work_item_to_work_item` from `clearline.ontology.v1`
- **ADO validation script** (`scripts/validate_ado_adapter.py`) — fetches all work items from Meridian Engineering, loads revisions, runs the adapter, and prints field coverage plus unmapped states
- **Ontology test suite** (`tests/test_ontology.py`) — pytest coverage for core models, mapping governance, diagnostic reliability scoring, and GitLab/GitHub/Bitbucket adapter transforms (IMUA-37)

### Fixed

- **Jira batch** — migrated from deprecated `GET /rest/api/3/search` to `POST /rest/api/3/search/jql` with `nextPageToken` pagination (Atlassian removed the legacy endpoint)
- **Jira adapter** — `started_at` confidence is now `MISSING` when no `IN_PROGRESS` state transition exists in changelog history (previously marked `INFERRED` on all items)

## [0.1.0] — 2026-06-23

### Added

- **Jira adapter** (`clearline/adapters/jira.py`) — transforms raw Jira API issue dicts (with changelog expanded) into canonical `WorkItem` objects; tracks unmapped statuses and unsupported changelog fields
- **Parity validator** (`clearline/parity.py`) — tool-agnostic `generate_parity_report()` for field coverage, transition fidelity, and distribution metrics
- **Meridian batch script** (`clearline/adapters/jira_batch.py`) — fetches all MRDN project issues from Jira, runs parity validation, writes `reports/meridian_parity.json`
- `.env.example`, `.gitignore`, and `reports/` directory for generated output
- **Installable package** (`pyproject.toml`) — editable install via `pip install -e ".[dev]"` (IMUA-38)
- **Clearline ontology v1** (`clearline/ontology/v1/`) — canonical `WorkItem`, `StateTransition`, `CanonicalState`, `ConfidenceLevel`, mapping layer, and diagnostic reliability models (IMUA-32)
