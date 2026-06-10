## Why

Backtest execution still applies BUY/SELL decisions through local cash/share checks, while the new pre-trade risk gate is not exercised by the existing simulation path. Integrating the gate into backtest execution makes research, paper, and future live paths converge on the same deterministic safety boundary.

## What Changes

- Route plain backtest BUY/SELL execution through `PreTradeRiskEngine` before mutating simulated portfolio state.
- Route target-weight trade conversion through the same gate so allocation-generated trades record deterministic risk adjustments/rejections.
- Preserve backtest behavior for valid cash-limited and position-limited trades while making non-positive prices explicit HOLD/rejection outcomes.
- Add focused tests that verify backtest helpers use risk-gate semantics and expose machine-readable risk reasons on decisions.

## Capabilities

### New Capabilities

### Modified Capabilities
- `pretrade-risk-gate`: Backtest execution helpers must use the deterministic pre-trade risk gate before applying simulated trades.

## Impact

- Affects `backtest/execution.py` and tests around execution helpers.
- Does not add a broker adapter or live order submission.
- Does not change existing model decision generation; only the execution boundary is hardened.
