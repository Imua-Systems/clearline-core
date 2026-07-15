# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added

- **`EstimateTransition` ontology type and `WorkItem.estimate` / `estimate_history`** (`clearline/ontology/v1/core.py`) — timestamped story-point changes (`from_value`/`to_value` as `Optional[float]`, `transitioned_at`, `transitioned_by`, `source_field`) plus current-state estimate for disclosure; Jira adapter maps `customfield_10016` ("Story Points") changelog and current value, excludes Story Points from unsupported-field tracking, and sets `field_confidence["estimate_history"]` to `explicit` when the changelog was evaluated (including empty confirmed-absence) or `missing` when changelog is absent; `jira_batch` now requests `customfield_10016` for current-state estimate (IMUA-135). Native time fields, issue-type/parent history, and non-Jira adapters are out of scope.
- **`PriorityChangeKind` enum** (`clearline/ontology/v1/core.py`) — distinguishes explicit priority field changes (`priority`) from backlog rank/order movement (`rank`) on `PriorityTransition`
- **Rank history probe** (`scripts/probe_rank_history.py`) — fetches live Jira issues and reports priority-history transitions split by `change_kind` (IMUA-102)
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

- **Jira adapter** — `_extract_priority_history` now captures backlog drag-and-drop reprioritization emitted as changelog field `Rank` / `customfield_10019`, tagging each transition with `change_kind` and `source_field` so Priority Movement can distinguish rank movement from explicit priority edits; Rank is no longer reported as an unsupported changelog field (IMUA-102)
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
