# clearline-core

Code-owned foundation for [Clearline](https://imuasystems.com), Imua's delivery intelligence platform. This repository defines the canonical ontology, source-system adapters, and parity validation tooling used to assess data fidelity before diagnostics run.

## Package layout

```
clearline/
  ontology/v1/     Canonical models (WorkItem, StateTransition, ConfidenceLevel, …)
  adapters/        Source-system adapters (Jira, ADO)
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

The Jira adapter derives `started_at` from the first changelog transition into `IN_PROGRESS`. Items that never entered that state receive `started_at: null` with confidence `missing`.

The ADO adapter derives `started_at` from the first revision whose `System.State` maps to `IN_PROGRESS`, and builds `state_history` by comparing `System.State` across consecutive revisions.

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

Tests cover `WorkItem`, `StateTransition`, `FieldMapping`, `MappingSet`, `DiagnosticReliability`, and `FailureModeDiagnostic`.
