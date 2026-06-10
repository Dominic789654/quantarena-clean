## Why

Recent fixed and multi-personality backtests still depend on unstable live data paths: US benchmark fetches can hit yfinance rate limits, Smart Beta market data can surface CN Tushare errors in US runs, and company-news signals are empty unless replay fixtures are explicitly wired in. This change makes the fixed verification path deterministic enough to trust after each strategy or execution change.

## What Changes

- Add a fixed multi-personality benchmark mode that runs the established AAPL/MSFT/NVDA 2026-06-01 through 2026-06-05 scenario with the five production personalities.
- Allow fixed benchmark invocations to carry deterministic data-source settings, including benchmark cache directory and company-news replay fixture path, into child backtest processes.
- Prevent US Smart Beta market-data preparation from falling through to CN-only Tushare logic when the US index provider and synthetic US proxy are unavailable.
- Preserve benchmark/news diagnostics and artifact review results in fixed benchmark summaries so data-source failures are visible without reading terminal logs.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `fixed-backtest-benchmark-runner`: Add fixed multi-personality benchmark execution and deterministic data-source configuration for fixed runs.
- `benchmark-data-provider-cache`: Require US benchmark/index paths to avoid CN-only providers and diagnose deterministic cache/replay usage clearly.

## Impact

- Affected code: `quantarena/fixed_backtest_benchmark.py`, `scripts/run_fixed_backtest_week.py`, `backtest/smart_beta_engine.py`, focused tests, and OpenSpec specs.
- Affected workflows: local fixed benchmark runs and post-change verification for single and multi-personality backtests.
- No breaking CLI changes; existing `simple`, `llm`, and `both` fixed benchmark modes remain compatible.
