# clearline-core

Code-owned foundation for [Clearline](https://imuasystems.com), Imua's delivery intelligence platform. This repository defines the canonical ontology, source-system adapters, and parity validation tooling used to assess data fidelity before diagnostics run.

## Package layout

```
clearline/
  ontology/v1/     Canonical models (WorkItem, StateTransition, ConfidenceLevel, …)
  adapters/        Source-system adapters (Jira today; others later)
  parity.py        Tool-agnostic parity report generator
reports/           Generated parity reports (gitignored)
```

## Requirements

- Python 3.11+
- `pydantic`, `httpx`, `python-dotenv`

```bash
pip install pydantic httpx python-dotenv
```

## Quick start

### Transform a single Jira issue (offline)

```bash
python -m clearline.adapters.jira
```

Runs against the built-in MRDN-25 sample and prints the canonical `WorkItem` as JSON.

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

   This fetches all issues from the **MRDN** project (with changelog expanded), transforms each into a `WorkItem`, generates a parity report, writes `reports/meridian_parity.json`, and prints a human-readable summary to stdout.

## Ontology

The canonical ontology lives at `clearline/ontology/v1/`:

| Module | Purpose |
|---|---|
| `core.py` | `WorkItem`, `StateTransition`, `CanonicalState`, `ConfidenceLevel` |
| `mapping.py` | `FieldMapping`, `MappingSet` — agent-assisted field mappings |
| `reliability.py` | `DiagnosticReliability`, `FailureModeDiagnostic` |

Ontology version: `clearline-ontology-v1.0`

## Adapters

Adapters translate raw source-system payloads into canonical `WorkItem` objects. Each adapter is isolated — only `clearline/adapters/jira.py` references Jira concepts.

| Adapter | Entry point |
|---|---|
| Jira | `jira_issue_to_work_item(issue: dict) -> WorkItem` |
| Jira batch | `python -m clearline.adapters.jira_batch` |

## Parity validation

`generate_parity_report(items, adapter_meta=None)` in `clearline/parity.py` is tool-agnostic. It accepts a list of `WorkItem` objects and returns field coverage, transition fidelity, state distribution, and per-item confidence summaries. Adapter-specific observations (unmapped statuses, unsupported changelog fields) are passed through via `adapter_meta` without the parity layer interpreting them.

## Environment

| Variable | Description |
|---|---|
| `JIRA_EMAIL` | Atlassian account email for Basic auth |
| `JIRA_API_TOKEN` | Atlassian API token |

Never commit `.env` — use `.env.example` as a template.
