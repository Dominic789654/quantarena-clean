## ADDED Requirements

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
