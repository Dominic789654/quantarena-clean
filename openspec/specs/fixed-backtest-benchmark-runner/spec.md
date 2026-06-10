# fixed-backtest-benchmark-runner Specification

## Purpose
TBD - created by archiving change add-fixed-backtest-benchmark-runner. Update Purpose after archive.
## Requirements
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

### Requirement: Run Fixed Multi-Personality Mode
The system SHALL provide a fixed benchmark runner mode that executes the established one-week US scenario as a multi-personality backtest.

#### Scenario: Run multi-personality mode
- **WHEN** the fixed benchmark runner is invoked with mode `multi`
- **THEN** it SHALL run one multi-personality backtest for AAPL, MSFT, and NVDA from 2026-06-01 through 2026-06-05 with 10000 initial cash.

#### Scenario: Use production personality set
- **WHEN** the fixed benchmark runner builds the `multi` command
- **THEN** it SHALL include `macro_tactical`, `fundamental_value`, `behavioral_momentum`, `smart_beta_passive`, and `equal_weight_index` as the personality set.

#### Scenario: Review multi-personality artifacts
- **WHEN** the fixed `multi` run completes and a comparison report directory is generated
- **THEN** the runner summary SHALL include the multi-personality artifact review result and fail the mode if that review reports errors.

### Requirement: Propagate Fixed Data Source Controls
The system SHALL allow fixed benchmark runs to pass deterministic data-source controls into child backtest processes.

#### Scenario: Replay news fixture configured
- **WHEN** the fixed benchmark runner is invoked with a company-news replay fixture path
- **THEN** child backtest processes SHALL receive `COMPANY_NEWS_PROVIDER=replay` and `COMPANY_NEWS_REPLAY_PATH` set to that fixture path.

#### Scenario: Benchmark cache configured
- **WHEN** the fixed benchmark runner is invoked with a benchmark cache directory
- **THEN** child backtest processes SHALL receive `BENCHMARK_CACHE_DIR` set to that directory.

#### Scenario: Diagnostics paths summarized
- **WHEN** a fixed benchmark mode writes benchmark or news diagnostics artifacts
- **THEN** the runner summary SHALL include paths to those diagnostics artifacts.

