## 1. Runner Interface

- [x] 1.1 Add a fixed benchmark module with explicit scenario defaults and mode selection
- [x] 1.2 Add a script wrapper for `python scripts/run_fixed_backtest_week.py`

## 2. Benchmark Execution

- [x] 2.1 Invoke the existing `run.py` backtest CLI for simple, LLM, and both modes
- [x] 2.2 Discover report directories and generate `dashboard.html` for successful runs
- [x] 2.3 Write benchmark-level `summary.json` with configuration, run outputs, metrics, and failures

## 3. Verification

- [x] 3.1 Add focused unit tests for command construction, summary output, dashboard hooks, and failures
- [x] 3.2 Run focused tests and OpenSpec validation
