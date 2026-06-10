## ADDED Requirements

### Requirement: Run Fixed Benchmark Modes
The system SHALL provide a committed runner for the fixed US benchmark scenario
using AAPL, MSFT, and NVDA from 2026-06-01 through 2026-06-05 with 10000 initial
cash.

#### Scenario: Run simple mode
- **WHEN** the runner is invoked with mode `simple`
- **THEN** it SHALL run exactly one non-LLM backtest for the fixed benchmark
  scenario.

#### Scenario: Run LLM mode
- **WHEN** the runner is invoked with mode `llm`
- **THEN** it SHALL run exactly one LLM technical-analyst backtest for the fixed
  benchmark scenario.

#### Scenario: Run both modes
- **WHEN** the runner is invoked with mode `both`
- **THEN** it SHALL run the simple benchmark and the LLM technical benchmark in a
  deterministic order.

### Requirement: Generate Benchmark Artifacts
The system SHALL generate a benchmark dashboard and machine-readable benchmark
summary for completed fixed benchmark runs.

#### Scenario: Backtest mode succeeds
- **WHEN** a fixed benchmark backtest mode completes with a report directory
- **THEN** the runner SHALL generate a `dashboard.html` file in that report
  directory.

#### Scenario: Summary is written
- **WHEN** the fixed benchmark runner finishes one or more requested modes
- **THEN** it SHALL write a summary JSON containing the fixed configuration,
  requested mode, per-mode status, run id, report directory, dashboard path, and
  metrics when available.

#### Scenario: Machine-readable output is requested
- **WHEN** the runner is invoked with JSON output enabled
- **THEN** it SHALL print the same summary payload as JSON.

### Requirement: Report Benchmark Failures
The system SHALL preserve partial benchmark results and report failed modes
without hiding successful modes.

#### Scenario: One mode fails during both mode
- **WHEN** the runner is invoked with mode `both` and one requested mode fails
- **THEN** the summary SHALL include the failed mode with non-zero exit code and
  error text while retaining any successful mode output.

#### Scenario: Any requested mode fails
- **WHEN** one or more requested modes fail
- **THEN** the runner process SHALL exit non-zero after writing the summary JSON.
