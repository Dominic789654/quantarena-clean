## MODIFIED Requirements

### Requirement: Generate Benchmark Artifacts
The system SHALL generate a benchmark dashboard, machine-readable benchmark summary, and benchmark data diagnostics for completed fixed benchmark runs.

#### Scenario: Backtest mode succeeds
- **WHEN** a fixed benchmark backtest mode completes with a report directory
- **THEN** the runner SHALL generate a `dashboard.html` file in that report directory.

#### Scenario: Summary is written
- **WHEN** the fixed benchmark runner finishes one or more requested modes
- **THEN** it SHALL write a summary JSON containing the fixed configuration, requested mode, per-mode status, run id, report directory, dashboard path, benchmark source, benchmark diagnostics path when available, and metrics when available.

#### Scenario: Machine-readable output is requested
- **WHEN** the runner is invoked with JSON output enabled
- **THEN** it SHALL print the same summary payload as JSON.

#### Scenario: Benchmark diagnostics are preserved
- **WHEN** a fixed benchmark run records benchmark cache, live provider, or fallback diagnostics
- **THEN** the diagnostics SHALL be preserved in the report directory and referenced from the summary JSON.
