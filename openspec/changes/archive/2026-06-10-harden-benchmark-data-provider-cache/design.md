## Context

US benchmark curves currently call yfinance directly from `BacktestEngine._build_us_index_benchmark_curve()`. In live test runs, `^GSPC` can timeout or rate-limit, causing benchmark fallback to equal-weight basket. The fallback is acceptable, but repeated network calls make runs slower/noisier and the fallback reason is only visible in logs.

## Goals / Non-Goals

**Goals:**

- Prefer local benchmark close-price cache before live yfinance calls.
- Persist successful live benchmark close-price responses for repeatable later runs.
- Export count-only benchmark diagnostics alongside backtest artifacts.
- Preserve existing equal-weight fallback behavior when no index curve is available.

**Non-Goals:**

- Replace yfinance as a live benchmark provider.
- Build a full historical benchmark data service.
- Change benchmark metric formulas.
- Change smart-beta optimization objectives.

## Decisions

- Add a small `quantarena.benchmark_diagnostics` collector mirroring the existing news diagnostics pattern. This keeps diagnostics process-local, JSON-safe, and easy for report generation to drain.
- Add a file-backed benchmark cache helper under `backtest/benchmark_cache.py`. Cache files are stored as JSONL rows under `data/benchmark_cache/` by default, keyed by sanitized index code. The helper loads rows into a `pd.Series` and can test requested date coverage.
- Use environment variables for cache controls:
  - `BENCHMARK_CACHE_DIR` overrides the cache directory.
  - `BENCHMARK_CACHE_ENABLED=false` disables cache reads and writes.
- Keep fallback semantics unchanged: if cache misses and live provider fails/returns empty, backtest falls back to equal-weight basket and records why.
- Export diagnostics from `BacktestReportGenerator.generate_full_report()` so both fixed and multi-personality runs get the artifact without changing runner internals deeply.

## Risks / Trade-offs

- Cached benchmark data can become stale -> cache is date-keyed daily close data, so historical backtests are deterministic; users can delete or replace cache files if needed.
- A partial cache might hide missing dates -> cache use requires coverage for all requested trading days; otherwise live provider is attempted.
- Diagnostics are process-local -> report generation drains them per run, matching existing news diagnostics behavior.

## Migration Plan

- No migration required. Existing runs keep live yfinance behavior on first cache miss, then become cached if the live request succeeds.
- Rollback is setting `BENCHMARK_CACHE_ENABLED=false` or deleting the cache directory.
