# fixed-backtest-cache-warmup Specification

## Purpose
TBD - created by archiving change add-fixed-backtest-cache-warmup. Update Purpose after archive.
## Requirements
### Requirement: Produce Fixed Cache Warmup Plan
The system SHALL produce an actionable warmup plan for fixed backtest cache
inputs without fetching live data or mutating cache contents by default.

#### Scenario: Required caches are ready
- **WHEN** the fixed cache warmup command evaluates cache health and all
  required fixed-backtest inputs are ready
- **THEN** the warmup plan SHALL mark `ok` true and include no required actions.

#### Scenario: Required caches are missing
- **WHEN** one or more required fixed-backtest cache inputs are missing or
  insufficiently covered
- **THEN** the warmup plan SHALL mark `ok` false and include one action per
  unresolved required cache finding.

### Requirement: Describe Warmup Actions
The system SHALL describe cache warmup actions in a machine-readable format.

#### Scenario: Stock price cache missing
- **WHEN** stock-price DB cache coverage is missing for fixed benchmark tickers
- **THEN** the plan SHALL include an action identifying the ticker/date cache
  gap, target layer, and recommended next command or provider step.

#### Scenario: Benchmark cache missing
- **WHEN** benchmark close-price cache coverage is missing for `^GSPC`
- **THEN** the plan SHALL include an action identifying the benchmark cache path
  and recommended cache build step.

#### Scenario: News replay fixture missing
- **WHEN** the replay news fixture is missing, invalid, or not relevant to the
  fixed benchmark profile
- **THEN** the plan SHALL include an action identifying the fixture path and
  recommended replay fixture build step.

### Requirement: Expose Fixed Cache Warmup CLI
The system SHALL expose a CLI workflow for fixed cache warmup planning.

#### Scenario: JSON output requested
- **WHEN** the warmup CLI is invoked with JSON output
- **THEN** it SHALL print the complete warmup plan as JSON.

#### Scenario: Strict mode requested
- **WHEN** the warmup CLI is invoked in strict mode
- **THEN** it SHALL exit non-zero if required warmup actions remain.

#### Scenario: Dry run mode
- **WHEN** the warmup CLI is invoked without write options
- **THEN** it SHALL only inspect caches and produce a plan without changing any
  cache files.
