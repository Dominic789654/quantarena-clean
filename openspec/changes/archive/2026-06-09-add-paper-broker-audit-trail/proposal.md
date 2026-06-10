## Why

Backtests now route execution through `PaperBroker`, but the generated reports still only show final trades and portfolio snapshots. A broker audit trail is needed before moving toward live read-only adapters so each decision can be traced through risk validation, order creation, fill outcome, and portfolio impact.

## What Changes

- Add a broker audit event model that records decision, risk validation, paper order, fill, rejection, and resulting portfolio state for each attempted backtest execution.
- Export a machine-readable broker audit artifact in each backtest report directory without changing the existing `trades.csv`, metrics, or dashboard contracts.
- Preserve audit records for rejected executions, including risk-gate rejections and paper-broker fill rejections.
- Add tests that prove the audit trail connects trades to order/fill IDs and captures rejected attempts.

## Capabilities

### New Capabilities
- `paper-broker-audit-trail`: Machine-readable audit events for paper broker execution attempts.

### Modified Capabilities
- `backtest-paper-broker-execution`: Backtest report output includes a paper broker audit artifact for paper-broker-routed execution.

## Impact

- Affected code: `backtest/execution.py`, `backtest/engine.py`, `backtest/report.py`, and new audit helper code under `trading/` or `backtest/`.
- Affected artifacts: new `broker_audit.jsonl` or equivalent machine-readable audit file in generated backtest report directories.
- Affected tests: execution helper, report artifact validation, fixed benchmark runner, and CLI/report smoke coverage.
- No live trading behavior and no external dependencies.
