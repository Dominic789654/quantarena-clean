## MODIFIED Requirements

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
