## Context

The current backtest news path can use in-memory `ReplayNewsProvider` in tests, while production-style runs usually route through `Router.get_us_stock_news()` and FMP/Tavily/AKShare. FMP diagnostics now show count-only filter stages, but zero results still require interpreting those counts manually and there is no file-backed replay provider that normal backtest runs can select.

## Goals / Non-Goals

**Goals:**
- Provide a file-backed replay news provider for deterministic historical backtests.
- Allow router-level selection via environment/config without changing analyst logic.
- Keep live/latest providers anti-lookahead safe.
- Classify zero-news diagnostics with a stable `zero_reason`.

**Non-Goals:**
- Build or download a historical news dataset.
- Relax date filtering or intentionally allow future news in historical backtests.
- Change company-news sentiment prompts.

## Decisions

- Add `FileReplayNewsProvider` in `backtest.providers`. It will load JSON or JSONL from disk into the same ticker-keyed shape used by `ReplayNewsProvider`.
- Select replay news in `Router` when `COMPANY_NEWS_PROVIDER=replay` or `replay_strict`, using `COMPANY_NEWS_REPLAY_PATH` for the fixture. Explicit replay configuration fails fast on missing/unreadable fixtures.
- Record replay diagnostics in the provider layer with count-only fields. FMP keeps its endpoint stage diagnostics and adds a derived `zero_reason`.
- Use a small zero-reason classifier:
  - `provider_empty`: raw count is zero.
  - `future_only`: raw count is positive but date-filtered count is zero.
  - `ticker_miss`: date-filtered count is positive but ticker-filtered count is zero.
  - `filtered_empty`: filters removed all items for another reason.
  - `not_zero`: final count is positive.

## Risks / Trade-offs

- Fixture schema ambiguity -> support two common shapes only: `{ticker: [items...]}` and JSONL rows with a ticker/symbol field.
- Environment-based selection can be misconfigured -> explicit replay mode raises clear provider errors rather than falling back silently.
- Diagnostics are process-local -> report export already drains in-process diagnostics at comparison generation.
