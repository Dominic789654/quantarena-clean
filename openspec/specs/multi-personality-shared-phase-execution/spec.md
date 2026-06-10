# multi-personality-shared-phase-execution Specification

## Purpose
TBD - created by archiving change fix-shared-phase-specialized-audit. Update Purpose after archive.
## Requirements
### Requirement: Preserve Specialized Personality Semantics In Shared Phase
The system SHALL execute day-shared multi-personality backtests through each personality engine's specialized decision logic while reusing shared analyst signals.

#### Scenario: Fundamental value applies value filter
- **WHEN** a shared phase-1 multi-personality backtest includes `fundamental_value`
- **THEN** the `fundamental_value` engine SHALL apply its value filter and report value behavior metrics from the shared-signal execution path.

#### Scenario: Behavioral momentum applies momentum controls
- **WHEN** a shared phase-1 multi-personality backtest includes `behavioral_momentum`
- **THEN** the `behavioral_momentum` engine SHALL apply its volatility scaling and crash-breaker controls and report momentum behavior metrics from the shared-signal execution path.

#### Scenario: Shared signals remain reused
- **WHEN** a specialized personality uses shared pre-collected analyst signals
- **THEN** the backtest SHALL avoid recomputing the analyst phase for that personality and day.

### Requirement: Review Backtest Log Artifacts For Execution Consistency
The development workflow SHALL include a post-run artifact review for multi-personality backtests before treating comparison results as valid.

#### Scenario: Trade and audit artifact consistency check
- **WHEN** a multi-personality backtest run completes and generated report artifacts are available
- **THEN** the review SHALL compare each personality's `trades.csv` with `broker_audit.jsonl` and flag any personality with trades but missing audit events.

#### Scenario: Specialized metric sanity check
- **WHEN** a multi-personality backtest includes specialized personalities
- **THEN** the review SHALL inspect their specialized behavior metrics for evidence that the intended specialized path executed.

### Requirement: Export Daily Personality Decisions
The system SHALL export a machine-readable daily decision artifact for day-shared multi-personality backtest runs.

#### Scenario: Daily decisions artifact generated
- **WHEN** a day-shared multi-personality backtest generates a comparison report
- **THEN** the comparison report directory SHALL contain `daily_decisions.jsonl` with one JSON object per date, personality, and ticker decision.

#### Scenario: Hold decisions preserved
- **WHEN** a personality emits a HOLD decision for a ticker on a trading day
- **THEN** the daily decision artifact SHALL include that HOLD decision with date, personality, ticker, action, shares, price when available, and justification when available.

#### Scenario: Applied execution state preserved
- **WHEN** a personality emits a decision with execution metadata such as `_applied` or risk reasons
- **THEN** the daily decision artifact SHALL include equivalent machine-readable fields without requiring consumers to parse logs.

#### Scenario: Smart beta applied state is explicit
- **WHEN** a day-shared multi-personality backtest includes `smart_beta_passive`
- **THEN** each Smart Beta daily decision row SHALL include a boolean `applied` value rather than `null`.

