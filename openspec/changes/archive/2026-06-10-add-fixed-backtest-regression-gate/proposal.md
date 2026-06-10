## Why

The fixed one-week backtest is now repeatable, but it still relies on manual log
inspection to decide whether a run regressed. We need a machine-readable gate so
simple and multi-personality fixed backtests can fail fast when metrics,
artifact reviews, or deterministic data-source diagnostics drift.

## What Changes

- Add a fixed backtest regression gate that compares a runner summary against a
  committed baseline with explicit tolerances.
- Validate both fixed simple and fixed multi-personality expectations, including
  run success, artifact review status, metrics, benchmark diagnostics, and news
  diagnostics.
- Add a CLI entrypoint that can optionally run the fixed benchmark first and then
  evaluate the generated summary.
- Change fixed benchmark summaries to reference full child process logs by path
  and retain only bounded output tails in summary JSON.

## Capabilities

### New Capabilities
- `fixed-backtest-regression-gate`: Defines the baseline comparison and CLI gate
  for fixed backtest benchmark summaries.

### Modified Capabilities
- `fixed-backtest-benchmark-runner`: Summaries must externalize child stdout and
  stderr while retaining concise tails for debugging.

## Impact

- Affected code: fixed backtest benchmark runner, new regression-gate module or
  script, fixed benchmark tests, and committed fixed benchmark baseline data.
- Affected workflows: local verification and future CI can run the gate after
  deterministic fixed simple and multi-personality backtests.
