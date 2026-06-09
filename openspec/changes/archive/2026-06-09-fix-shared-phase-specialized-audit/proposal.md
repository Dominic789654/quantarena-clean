## Why

The short multi-personality backtest exposed an execution-path bug: shared phase-1 orchestration can bypass specialized personality logic, and some LLM-routed trades are missing paper broker audit events. This needs to be fixed before using personality comparisons as evidence for market-facing behavior.

## What Changes

- Route shared phase-1 personality execution through each specialized engine's own precollected-signal hook when available.
- Ensure LLM smart-priority decisions executed in backtests use the same paper-broker/audit execution helpers as other backtest orders.
- Add regression coverage that checks both specialized behavior and audit artifacts for shared multi-personality runs.
- Record the log-review findings in the development workflow so future backtest result reviews explicitly check trade/audit consistency.

## Capabilities

### New Capabilities
- `multi-personality-shared-phase-execution`: Ensures day-shared multi-personality backtests preserve specialized personality execution semantics when reusing shared analyst signals.

### Modified Capabilities
- `paper-broker-audit-trail`: Extend audit coverage to smart-priority LLM backtest executions in shared multi-personality mode.

## Impact

- Affected code: `backtest/engine.py`, `backtest/multi_personality_engine.py`, specialized personality engines, and regression tests.
- Affected artifacts: generated `broker_audit.jsonl`, `trades.csv`, metrics JSON, and multi-personality comparison outputs.
- No CLI breaking changes are expected.
