## Why

Recent fixed and multi-personality US backtests completed, but benchmark and smart-beta paths hit `^GSPC` yfinance timeout/rate-limit errors and fell back to equal-weight baskets. Backtest benchmark data should be replayable from local cache first and should expose machine-readable diagnostics when it must fall back.

## What Changes

- Add a local benchmark data cache for index/ETF daily close series used by backtest benchmark curves.
- Use cached benchmark prices before attempting live yfinance downloads.
- Write successful live benchmark downloads back to cache for later deterministic reruns.
- Add count-only benchmark diagnostics for cache hit, live fetch success, live fetch failure, and fallback source.
- Keep equal-weight basket fallback behavior, but make the reason inspectable.

## Capabilities

### New Capabilities

- `benchmark-data-provider-cache`: Cached benchmark data loading, live refresh, and diagnostics for benchmark curves.

### Modified Capabilities

- `fixed-backtest-benchmark-runner`: Fixed benchmark runs must surface benchmark source/fallback diagnostics.

## Impact

- Affected code: `backtest/engine.py`, benchmark diagnostics helper/module, fixed benchmark tests and benchmark-related engine tests.
- Affected artifacts: backtest `metrics.json`/comparison data already include `benchmark_source`; diagnostics may be exported as JSONL in report directories.
- No new external dependencies.
