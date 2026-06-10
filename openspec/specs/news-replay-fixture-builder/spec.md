# news-replay-fixture-builder Specification

## Purpose
TBD - created by archiving change add-news-replay-fixture-builder. Update Purpose after archive.
## Requirements
### Requirement: Normalize Local News Exports
The system SHALL build replay news fixtures from local JSON, JSONL, or CSV news exports without network access.

#### Scenario: JSON array input is normalized
- **WHEN** the builder reads a local JSON file containing news item objects with common ticker and publish-time aliases
- **THEN** it SHALL emit canonical rows containing ticker, title, publish_time, publisher when available, and preserved JSON-safe metadata.

#### Scenario: JSONL input is normalized
- **WHEN** the builder reads a local JSONL file with one news item object per line
- **THEN** it SHALL normalize each valid row into the canonical replay fixture schema.

#### Scenario: CSV input is normalized
- **WHEN** the builder reads a local CSV file with supported column aliases
- **THEN** it SHALL normalize each valid row into the canonical replay fixture schema.

#### Scenario: Ticker-keyed JSON input is normalized
- **WHEN** the builder reads a ticker-keyed JSON object whose values are news item lists
- **THEN** it SHALL apply the object key as the ticker for rows that do not define a ticker field.

### Requirement: Validate Replay-Compatible Output
The system SHALL write deterministic JSONL output that can be loaded by the replay news provider.

#### Scenario: Output ordering is deterministic
- **WHEN** multiple valid rows are generated from an input file
- **THEN** the output rows SHALL be sorted by ticker, publish_time, and title before writing.

#### Scenario: Fixture validation succeeds
- **WHEN** the builder writes an output fixture
- **THEN** it SHALL validate the fixture by loading it through the file replay news provider.

#### Scenario: Invalid rows fail by default
- **WHEN** an input row is missing a ticker, title, or parseable publish time
- **THEN** the builder SHALL fail with a clear row-specific error by default.

#### Scenario: Invalid rows can be skipped
- **WHEN** skip-invalid mode is enabled and some rows are invalid
- **THEN** the builder SHALL skip invalid rows, write valid rows, and report invalid row counts.

### Requirement: Expose Fixture Builder CLI
The system SHALL expose the fixture builder through the QuantArena CLI.

#### Scenario: CLI writes fixture
- **WHEN** a user runs the CLI with an input path and output path
- **THEN** the CLI SHALL write the replay fixture and print a machine-readable summary when JSON output is requested.

#### Scenario: CLI reports validation errors
- **WHEN** fixture building fails due to invalid input
- **THEN** the CLI SHALL return a non-zero exit code and report the error.

