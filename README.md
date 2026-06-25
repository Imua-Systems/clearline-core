# clearline-core

Code-owned foundation for [Clearline](https://imuasystems.com), Imua's delivery intelligence platform. This repository defines the canonical ontology, source-system adapters, and parity validation tooling used to assess data fidelity before diagnostics run.

## Package layout

```
clearline/
  ontology/v1/     Canonical models (WorkItem, StateTransition, ConfidenceLevel, …)
  adapters/        Source-system adapters (Jira, ADO, Linear, GitLab, GitHub Issues, Bitbucket)
  connectors/      Live API connectors and fetch dispatch (SourceConnection)
  parity.py        Tool-agnostic parity report generator
scripts/           Live adapter validation scripts
reports/           Generated parity reports (gitignored)
```

## Requirements

- Python 3.11+

Install the package with dev dependencies:

```bash
pip install -e ".[dev]"
```

Runtime dependencies (`pydantic`, `httpx`, `python-dotenv`) are installed automatically.

## Quick start

### Transform a single Jira issue (offline)

```bash
python -m clearline.adapters.jira
```

Runs against the built-in MRDN-25 sample and prints the canonical `WorkItem` as JSON.

### Transform a single ADO work item (offline)

```bash
python -m clearline.adapters.ado
```

Runs against the built-in Meridian sample and prints the canonical `WorkItem` as JSON.

### Transform a single GitLab issue (offline)

```bash
python -m clearline.adapters.gitlab
```

Runs against the built-in Meridian sample and prints the canonical `WorkItem` as JSON.

### Transform a single GitHub issue (offline)

```bash
python -m clearline.adapters.github_issues
```

Runs against the built-in Meridian sample and prints the canonical `WorkItem` as JSON.

### Transform a single Bitbucket issue (offline)

```bash
python -m clearline.adapters.bitbucket
```

Runs against the built-in Meridian sample and prints the canonical `WorkItem` as JSON.

### Generate a parity report from a sample issue

```bash
python -m clearline.parity
```

### Batch: Meridian project parity report

1. Copy `.env.example` to `.env` and set your Jira credentials:

   ```
   JIRA_EMAIL=you@imuasystems.com
   JIRA_API_TOKEN=your-api-token
   ```

2. Run the batch script:

   ```bash
   python -m clearline.adapters.jira_batch
   ```

   This fetches all issues from the **MRDN** project (with changelog expanded) via `POST /rest/api/3/search/jql`, transforms each into a `WorkItem`, generates a parity report, writes `reports/meridian_parity.json`, and prints a human-readable summary to stdout.

### Validate: ADO Meridian Engineering adapter

1. Set your Azure DevOps PAT in `.env` or the environment:

   ```
   ADO_PAT=your-personal-access-token
   ```

2. Run the validation script:

   ```bash
   python scripts/validate_ado_adapter.py
   ```

   This fetches all work items from **Meridian Engineering** via WIQL, loads full items and revision history, transforms each through `ado_work_item_to_work_item`, and prints a per-item table, field coverage summary, errors, and any unmapped ADO states.

### Fetch work items via connectors

Connectors fetch live data from source systems and return canonical `WorkItem` lists. Configure a `SourceConnection` and call `fetch_work_items()`:

```python
from clearline.connectors.fetch import SourceConnection, fetch_work_items

# GitLab
conn = SourceConnection(
    source_system="gitlab",
    api_token="your-gitlab-token",
    project_key="group/project",
)
items = fetch_work_items(conn)

# GitHub Issues
conn = SourceConnection(
    source_system="github_issues",
    base_url="https://api.github.com",
    api_token="your-github-token",
    project_key="owner/repo",
)
items = fetch_work_items(conn)

# Bitbucket
conn = SourceConnection(
    source_system="bitbucket",
    base_url="https://api.bitbucket.org/2.0",
    api_token="your-bitbucket-token",
    project_key="workspace/repo_slug",
)
items = fetch_work_items(conn)
```

| Connector | `source_system` | `project_key` format | Default `base_url` |
|---|---|---|---|
| GitLab | `gitlab` | Project ID or `group/project` path | `https://gitlab.com` |
| GitHub Issues | `github_issues` | `owner/repo` | `https://api.github.com` |
| Bitbucket | `bitbucket` | `workspace/repo_slug` | `https://api.bitbucket.org/2.0` |

GitLab fetches issues updated within `analysis_window_days` (default 90) and loads `resource_state_events` per issue. GitHub fetches all issues (excluding pull requests) and loads issue timeline events per issue. Bitbucket fetches issues updated within the analysis window and loads issue changes per issue; if issues are disabled for the repository, the connector returns an empty list without raising an error.

## Ontology

The canonical ontology lives at `clearline/ontology/v1/`:

| Module | Purpose |
|---|---|
| `core.py` | `WorkItem`, `StateTransition`, `CanonicalState`, `ConfidenceLevel` |
| `mapping.py` | `FieldMapping`, `MappingSet` — agent-assisted field mappings |
| `reliability.py` | `DiagnosticReliability`, `FailureModeDiagnostic` |

Ontology version: `clearline-ontology-v1.0`

## Adapters

Adapters translate raw source-system payloads into canonical `WorkItem` objects. Each adapter is isolated — only its own module references source-system concepts.

| Adapter | Entry point |
|---|---|
| Jira | `jira_issue_to_work_item(issue: dict) -> WorkItem` |
| Jira (mapped) | `mapped_issue_to_work_item(issue: dict) -> WorkItem` |
| Jira batch | `python -m clearline.adapters.jira_batch` |
| ADO | `ado_work_item_to_work_item(item: dict, revisions: list[dict] \| None) -> WorkItem` |
| ADO validate | `python scripts/validate_ado_adapter.py` |
| Linear | `linear_issue_to_work_item(issue: dict) -> WorkItem` |
| GitLab | `gitlab_issue_to_work_item(issue: dict, events: list[dict] \| None) -> WorkItem` |
| GitHub Issues | `github_issue_to_work_item(issue: dict, events: list[dict] \| None) -> WorkItem` |
| Bitbucket | `bitbucket_issue_to_work_item(issue: dict, changes: list[dict] \| None) -> WorkItem` |

The Jira adapter derives `started_at` from the first changelog transition into `IN_PROGRESS`. Items that never entered that state receive `started_at: null` with confidence `missing`.

The ADO adapter derives `started_at` from the first revision whose `System.State` maps to `IN_PROGRESS`, and builds `state_history` by comparing `System.State` across consecutive revisions.

The GitLab adapter builds `state_history` from `resource_state_events` and maps milestone titles to `sprint_id`.

The GitHub Issues adapter builds `state_history` from `closed` and `reopened` timeline events only. Optional fields (milestone, assignee, labels) degrade to `None` without marking confidence as `missing`. Pull requests returned by the issues endpoint are excluded at the connector layer.

The Bitbucket adapter builds `state_history` from issue status changes only. Priority is stored in `labels` (not canonical `priority`); component name is mapped as a label proxy. Optional fields degrade gracefully; if issues are disabled for the repository, the connector returns an empty list.

## Parity validation

`generate_parity_report(items, adapter_meta=None)` in `clearline/parity.py` is tool-agnostic. It accepts a list of `WorkItem` objects and returns field coverage, transition fidelity, state distribution, and per-item confidence summaries. Adapter-specific observations (unmapped statuses, unsupported changelog fields) are passed through via `adapter_meta` without the parity layer interpreting them.

## Environment

| Variable | Description |
|---|---|
| `JIRA_EMAIL` | Atlassian account email for Basic auth |
| `JIRA_API_TOKEN` | Atlassian API token |
| `ADO_PAT` | Azure DevOps personal access token (empty username Basic auth) |

Never commit `.env` — use `.env.example` as a template.

## Testing

Run the ontology test suite with coverage:

```bash
python -m pytest tests/ -v --cov=clearline.ontology --cov-report=term-missing
```

Tests cover `WorkItem`, `StateTransition`, `FieldMapping`, `MappingSet`, `DiagnosticReliability`, `FailureModeDiagnostic`, and adapter transforms for GitLab, GitHub Issues, and Bitbucket.
