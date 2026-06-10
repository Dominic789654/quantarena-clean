# benchmark-data-provider-cache Specification

## Purpose
TBD - created by archiving change harden-benchmark-data-provider-cache. Update Purpose after archive.
## Requirements
### Requirement: Load Cached Benchmark Prices
The system SHALL load benchmark index or ETF daily close prices from a local cache before attempting a live provider request.

#### Scenario: Cache hit serves benchmark curve
- **WHEN** a backtest requests a benchmark curve for an index code and the local cache contains daily close prices covering the requested trading days
- **THEN** the benchmark curve SHALL be built from cached prices without calling the live provider.

#### Scenario: Cache miss attempts live provider
- **WHEN** a backtest requests a benchmark curve and the local cache does not cover the requested trading days
- **THEN** the system SHALL attempt the configured live benchmark provider before falling back to an equal-weight basket.

#### Scenario: Live success warms cache
- **WHEN** the live benchmark provider returns usable daily close prices
- **THEN** the system SHALL write those prices to the local benchmark cache for later runs.

### Requirement: Diagnose Benchmark Provider Fallbacks
The system SHALL record machine-readable benchmark data diagnostics for benchmark cache use, live fetches, and fallback decisions.

#### Scenario: Cache hit diagnostic
- **WHEN** cached benchmark prices are used
- **THEN** the diagnostics SHALL record index code, start date, end date, provider `cache`, status `hit`, row count, and benchmark source.

#### Scenario: Live provider failure diagnostic
- **WHEN** a live benchmark provider request fails or returns no usable data
- **THEN** the diagnostics SHALL record index code, provider name, status `error` or `empty`, sanitized error type/message when available, and the fallback source.

#### Scenario: Equal-weight fallback diagnostic
- **WHEN** the system falls back to the equal-weight basket because no index benchmark curve is available
- **THEN** the diagnostics SHALL record fallback source `equal_weight_basket` and the reason.

#### Scenario: Diagnostics are exported
- **WHEN** a backtest report is generated
- **THEN** the report directory SHALL contain benchmark diagnostics as JSON lines when benchmark diagnostics were recorded.

