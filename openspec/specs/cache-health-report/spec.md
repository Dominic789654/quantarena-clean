# cache-health-report Specification

## Purpose
TBD - created by archiving change add-cache-health-report. Update Purpose after archive.
## Requirements
### Requirement: Report Cache Layer Readiness
The system SHALL provide a cache health report that inspects configured cache
layers without fetching live data or mutating cache contents.

#### Scenario: All required cache layers are ready
- **WHEN** the health report evaluates a profile whose required cache inputs are
  present and sufficiently covered
- **THEN** the report SHALL mark `ok` true and include per-layer `hit` statuses.

#### Scenario: Required cache layer is missing
- **WHEN** a required cache input is absent, unreadable, or insufficiently
  covered
- **THEN** the report SHALL mark `ok` false and include a finding identifying
  the layer, path or key, and reason.

### Requirement: Support Fixed Backtest Cache Profile
The system SHALL include a fixed-backtest cache profile for the committed
one-week US benchmark scenario.

#### Scenario: Fixed profile checks stock prices
- **WHEN** the fixed-backtest profile is evaluated
- **THEN** the report SHALL check cached stock-price coverage for AAPL, MSFT, and
  NVDA from 2026-06-01 through 2026-06-05.

#### Scenario: Fixed profile checks benchmark cache
- **WHEN** the fixed-backtest profile is evaluated
- **THEN** the report SHALL check cached benchmark closes for `^GSPC` over the
  same trading dates.

#### Scenario: Fixed profile checks news replay
- **WHEN** the fixed-backtest profile is evaluated with a replay news fixture
- **THEN** the report SHALL check that the fixture exists and contains parseable
  replay rows for the fixed benchmark tickers or dates.

### Requirement: Expose Cache Health CLI
The system SHALL expose a command-line cache health workflow with
machine-readable and human-readable output.

#### Scenario: JSON output requested
- **WHEN** the cache health CLI is invoked with JSON output
- **THEN** it SHALL print the complete report payload as JSON.

#### Scenario: Strict mode requested
- **WHEN** the cache health CLI is invoked in strict mode
- **THEN** it SHALL exit non-zero when the report is not ok.

#### Scenario: Non-strict mode requested
- **WHEN** the cache health CLI is invoked without strict mode
- **THEN** it SHALL print the report and exit zero even when findings are
  present.

### Requirement: Provide Warmup Planning Inputs
The system SHALL expose cache health findings and layer details in a stable
shape that fixed-backtest warmup planning can consume.

#### Scenario: Required cache finding reported
- **WHEN** a required cache layer is missing or insufficiently covered
- **THEN** the health report SHALL include the layer name, cache path or key,
  reason, and per-layer details needed to construct a warmup action.

#### Scenario: Required cache layer ready
- **WHEN** a required cache layer is ready
- **THEN** the health report SHALL include enough per-layer details to explain
  why no warmup action is required.
