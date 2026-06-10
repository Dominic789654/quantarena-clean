# backtest-news-diagnostics Specification

## Purpose
TBD - created by archiving change add-backtest-decision-news-diagnostics. Update Purpose after archive.
## Requirements
### Requirement: Record Company News Fetch Diagnostics
The system SHALL record machine-readable company-news fetch diagnostics for backtest news requests.

#### Scenario: FMP news returns zero usable items
- **WHEN** a backtest requests company news through the FMP provider and the final usable news item count is zero
- **THEN** the diagnostics SHALL record provider, market, ticker, trading date, raw row count, date-filtered count, ticker-filtered count, topic-filtered count when applicable, final item count, and endpoint stages.

#### Scenario: News diagnostics are exported
- **WHEN** a multi-personality comparison report is generated after company-news analysis
- **THEN** the comparison report directory SHALL contain `news_diagnostics.jsonl` with one JSON object per recorded news request.

#### Scenario: Diagnostics do not expose raw news payloads
- **WHEN** company-news diagnostics are written
- **THEN** the diagnostics SHALL contain counts, provider metadata, and filter-stage metadata only, not full raw article content.

