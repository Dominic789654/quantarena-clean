## MODIFIED Requirements

### Requirement: Record Company News Fetch Diagnostics
The system SHALL record machine-readable company-news fetch diagnostics for backtest news requests, including a zero-result reason when no usable news items are returned.

#### Scenario: FMP news returns zero usable items
- **WHEN** a backtest requests company news through the FMP provider and the final usable news item count is zero
- **THEN** the diagnostics SHALL record provider, market, ticker, trading date, raw row count, date-filtered count, ticker-filtered count, topic-filtered count when applicable, final item count, endpoint stages, and `zero_reason`.

#### Scenario: Replay news returns zero usable items
- **WHEN** a backtest requests company news through a replay news provider and the final usable news item count is zero
- **THEN** the diagnostics SHALL record provider `replay_news`, ticker, trading date, raw row count, date-filtered count, final item count, and `zero_reason`.

#### Scenario: News diagnostics are exported
- **WHEN** a multi-personality comparison report is generated after company-news analysis
- **THEN** the comparison report directory SHALL contain `news_diagnostics.jsonl` with one JSON object per recorded news request.

#### Scenario: Diagnostics do not expose raw news payloads
- **WHEN** company-news diagnostics are written
- **THEN** the diagnostics SHALL contain counts, provider metadata, filter-stage metadata, and zero-result classification only, not full raw article content.
