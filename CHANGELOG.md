# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added

- **Ontology test suite** (`tests/test_ontology.py`) — pytest coverage for core models, mapping governance, and diagnostic reliability scoring (IMUA-37)

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
