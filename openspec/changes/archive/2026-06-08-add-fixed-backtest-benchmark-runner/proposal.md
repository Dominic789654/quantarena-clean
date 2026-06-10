## Why

QuantArena now has a repeatable backtest engine, a pre-trade risk gate, and an
offline HTML visualizer, but the fixed one-week benchmark used during development
still lives as manually remembered shell commands. A committed runner makes the
same scenario easy to rerun after risk, execution, data, or LLM changes.

## What Changes

- Add a fixed benchmark runner for the US one-week AAPL/MSFT/NVDA scenario.
- Support `simple`, `llm`, and `both` modes from a stable script entry point.
- Generate each run's existing backtest report artifacts and HTML dashboard.
- Write a machine-readable summary JSON that records the fixed configuration,
  per-mode run ids, report paths, dashboard paths, metrics, and failures.
- Keep provider and LLM behavior opt-in through the existing environment and
  `run.py` validation flow.

## Capabilities

### New Capabilities
- `fixed-backtest-benchmark-runner`: Runs a fixed backtest benchmark scenario and
  records reproducible report and dashboard outputs.

### Modified Capabilities
None.

## Impact

- Adds a runner module and a script wrapper under `scripts/`.
- Adds focused tests for command construction, summary generation, failure
  reporting, and dashboard generation hooks.
- Reuses `run.py` and `quantarena.backtest_visualizer`; no new runtime
  dependency or external charting dependency is introduced.
