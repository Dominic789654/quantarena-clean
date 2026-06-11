## Why

The cache health report can identify missing fixed-backtest inputs, but it does
not tell the operator what action to take next. A warmup plan closes that gap by
turning health findings into an explicit, machine-readable preparation plan
before fixed backtests or regression gates run.

## What Changes

- Add a fixed backtest cache warmup plan command that reuses cache health checks.
- Default to dry-run mode: inspect caches and output required actions without
  fetching live data or writing cache files.
- Provide structured actions for stock price DB cache, benchmark cache, and news
  replay fixture readiness.
- Add strict behavior that fails when required warmup actions remain unresolved.

## Capabilities

### New Capabilities
- `fixed-backtest-cache-warmup`: Produces an actionable warmup plan for the
  fixed one-week benchmark cache inputs.

### Modified Capabilities
- `cache-health-report`: Cache health results are reusable as the source of
  fixed-backtest warmup planning.

## Impact

- Affected code: new warmup module/script, cache CLI integration, tests, and
  OpenSpec specs.
- No network provider calls and no cache writes in this change.
