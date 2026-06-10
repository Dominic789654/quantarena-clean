## Context

The project already has reusable pieces for deterministic backtests: benchmark close caching, replay news fixtures, a fixed one-week single-backtest runner, and multi-personality artifact review. The missing link is orchestration. The fixed runner cannot execute the five-personality scenario, cannot pass replay/cache settings into child runs, and Smart Beta US constituent lookup still tries the CN-only Tushare path before using its local US fallback.

## Goals / Non-Goals

**Goals:**
- Add a fixed multi-personality mode that uses the same AAPL/MSFT/NVDA one-week benchmark scenario.
- Let fixed benchmark runs pass benchmark cache and replay-news settings through environment variables in a controlled way.
- Include multi-personality artifact review and diagnostics references in fixed benchmark summaries.
- Route US index constituents away from Tushare so US Smart Beta runs do not emit irrelevant token errors.

**Non-Goals:**
- Add a new live market data provider.
- Change existing replay news filtering semantics.
- Make yfinance disappear from all code paths; cache misses may still use live providers outside deterministic fixed runs.
- Change the existing `simple`, `llm`, or `both` fixed benchmark mode behavior.

## Decisions

- Extend the existing fixed benchmark runner instead of creating a second script. This keeps the fixed scenario definition in one place and lets `scripts/run_fixed_backtest_week.py` remain the entry point.
- Add `multi` as a new fixed runner mode while keeping `both` as `simple + llm` for backward compatibility.
- Store child-process data-source settings on `FixedBenchmarkConfig` and pass them via `env` to `subprocess.run`. This avoids changing `run.py` argument parsing for environment-owned provider selection.
- For `multi`, discover the comparison report directory from the existing "Detailed reports saved to:" output and review it with `review_multi_personality_artifacts`.
- Treat US index constituents as a US-safe fallback path in `IndexConstituentsProvider.get_constituents` by returning `_fetch_constituents_fallback` directly for caret-prefixed index codes.

## Risks / Trade-offs

- Multi-personality fixed mode can be slower than simple/LLM modes -> keep it opt-in via `--mode multi`.
- Replay fixtures are only deterministic when the caller supplies useful rows -> runner records the configured replay path and news diagnostics path, but does not fabricate news.
- Benchmark cache misses may still hit live providers -> fixed runs can provide `--benchmark-cache-dir`; tests cover env propagation and cache-first behavior rather than forbidding all live access globally.
