# backtest-news-replay-provider Specification

## Purpose
TBD - created by archiving change improve-backtest-news-replay-provider. Update Purpose after archive.
## Requirements
### Requirement: Replay Historical Company News
The system SHALL support deterministic replay of historical company-news fixtures for backtest company-news analysis.

#### Scenario: Replay fixture selected
- **WHEN** a backtest company-news request is configured with a replay news fixture path
- **THEN** the system SHALL load news from that fixture before calling live/latest company-news providers.

#### Scenario: Replay fixture enforces trading-date cutoff
- **WHEN** a replay fixture contains news published after the simulated trading date
- **THEN** the replay provider SHALL exclude those future-dated items from the returned news.

#### Scenario: Replay fixture keeps ticker isolation
- **WHEN** a replay fixture contains news for multiple tickers
- **THEN** a request for one ticker SHALL return only that ticker's replay news items.

#### Scenario: Missing replay fixture fails clearly
- **WHEN** replay news is explicitly configured but the fixture cannot be loaded
- **THEN** the system SHALL raise a structured provider error instead of silently falling back to live/latest news.

### Requirement: Preserve Live Provider Anti-Lookahead
The system SHALL preserve anti-lookahead filtering for live/latest news providers used in historical backtests.

#### Scenario: FMP latest feed has future-only rows
- **WHEN** FMP returns raw news rows whose publish dates are after the simulated trading date
- **THEN** those rows SHALL NOT be returned to the company-news analyst.

