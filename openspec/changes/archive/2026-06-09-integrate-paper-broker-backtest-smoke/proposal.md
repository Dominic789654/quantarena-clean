## Why

The local paper broker is now the intended bridge between research backtests and future broker adapters, but the backtest execution path still mutates portfolio dictionaries directly and the persisted paper state cannot safely submit orders after a reload. Fixing those gaps now gives the project a stable local execution contract before adding live read-only broker integrations.

## What Changes

- Preserve paper order and fill ID sequences across JSON state reloads so persistent paper portfolios can submit multiple orders over time.
- Route backtest buy/sell and target-allocation execution through `PaperBroker` while preserving the existing report, metrics, and trade-recording contract.
- Add a `quantarena paper smoke` command that runs a deterministic local paper portfolio lifecycle check and returns a machine-readable result.

## Capabilities

### New Capabilities
- `backtest-paper-broker-execution`: Backtest execution submits and fills broker-neutral orders through the local paper broker before recording trades and snapshots.

### Modified Capabilities
- `paper-broker-order-lifecycle`: Persisted paper broker state maintains monotonic order and fill IDs after reload.
- `paper-portfolio-command-interface`: The paper portfolio CLI exposes a deterministic smoke command for local lifecycle validation.

## Impact

- Affected code: `backtest/execution.py`, `backtest/engine.py`, `trading/paper_broker.py`, `trading/paper_portfolio.py`, `quantarena/cli.py`.
- Affected tests: paper broker, paper portfolio CLI, execution helper, fixed benchmark, and CLI tests.
- No new external dependencies and no live trading behavior.
