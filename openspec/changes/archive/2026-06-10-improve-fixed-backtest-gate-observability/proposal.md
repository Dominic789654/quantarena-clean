## Why

The fixed regression gate can now pass or fail runs, but a passing JSON result
does not show which checks actually ran. Recent backtest logs also show large
INFO/DEBUG streams in child process stderr, so warning/error clues need a bounded
machine-readable summary instead of manual log scanning.

## What Changes

- Add a checked-summary payload to gate results that records evaluated modes,
  metric checks, required personalities, diagnostics checks, and referenced log
  paths.
- Add bounded log issue extraction for fixed benchmark child stdout/stderr logs,
  surfacing warning/error lines without embedding full logs.
- Keep the gate pass/fail semantics unchanged: extracted warning lines are
  observability data unless a baseline check fails.

## Capabilities

### New Capabilities

### Modified Capabilities
- `fixed-backtest-regression-gate`: Gate results must include checked-summary
  and bounded log issue observability.

## Impact

- Affected code: fixed backtest regression gate result model, evaluator, CLI
  output, tests, and OpenSpec requirements.
- No changes to backtest strategy behavior, baseline tolerances, or regression
  pass/fail criteria.
