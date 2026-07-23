# report-citation-normalization Specification

## Purpose
TBD - created by archiving change fix-report-agent-citation-normalize-args. Update Purpose after archive.
## Requirements
### Requirement: Citation normalization completes on every report assembly path
Report generation SHALL apply citation normalization with the full citation-key-to-number map on every assembly path (incremental, non-incremental, and per-section), and SHALL NOT raise on any path.

#### Scenario: Non-incremental assembly normalizes citations
- **WHEN** `ReportAgent` is constructed with `incremental_edit=False` and `generate_report` runs with signals whose joined section length is below the incremental threshold
- **THEN** the final report is produced without error and citation markers are normalized using the key-to-number map

#### Scenario: Incremental assembly unchanged
- **WHEN** `generate_report` runs down the incremental path
- **THEN** citation normalization behaves exactly as before this change

