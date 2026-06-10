## Why

Historical backtests should not depend on latest-news feeds that primarily return articles after the simulated trading date. Recent diagnostics showed FMP returning raw rows while all usable company-news results were zero due to date or ticker filtering, so historical news needs an explicit replay-first path and clearer zero-result reasons.

## What Changes

- Add a replay news provider that can load deterministic company-news fixtures from JSON/JSONL files for historical backtests.
- Route company-news requests through the replay provider when configured, before falling back to live/latest providers.
- Keep anti-lookahead filtering: live/latest providers MUST NOT inject future-dated news into historical trading dates.
- Add `zero_reason` to company-news diagnostics so zero results are classified as `future_only`, `ticker_miss`, `provider_empty`, or `filtered_empty`.
- No breaking changes.

## Capabilities

### New Capabilities
- `backtest-news-replay-provider`: Historical company-news replay provider selection and fixture loading.

### Modified Capabilities
- `backtest-news-diagnostics`: Add zero-result reason classification for company-news diagnostics.

## Impact

- Affected code: `backtest/providers.py`, `deepfund/src/apis/router.py`, `deepfund/src/apis/fmp/api.py`, `quantarena/news_diagnostics.py`, workflow/news tests.
- New configuration: file path environment/config for replay news fixtures.
- No new external runtime dependencies.
