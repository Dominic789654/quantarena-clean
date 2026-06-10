## Why

QuantArena now converts advisory decisions into deterministic `OrderIntent`
objects, but simulated execution still lacks the order lifecycle that real
markets require. A paper broker layer lets the project test submission,
acceptance, fills, cancellations, portfolio updates, and reconciliation before
any live broker adapter is introduced.

## What Changes

- Add broker-neutral account, position, quote, order, and fill models.
- Add an in-memory order store for submitted paper orders.
- Add a paper broker that accepts risk-approved `OrderIntent` values and drives
  orders through submitted, accepted, rejected, filled, partial-filled, and
  cancelled states.
- Update paper account cash and positions from fills rather than direct strategy
  mutation.
- Provide account, position, order, quote, and reconciliation snapshot APIs.
- Keep all behavior local and deterministic; no live broker API or network calls.

## Capabilities

### New Capabilities
- `paper-broker-order-lifecycle`: Simulates broker order lifecycle and account
  state updates from fills for risk-approved paper orders.

### Modified Capabilities
None.

## Impact

- Adds `trading/broker.py`, `trading/order_store.py`, `trading/paper_broker.py`,
  and `trading/reconciliation.py`.
- Extends `trading/__init__.py` exports for broker/order lifecycle primitives.
- Adds focused tests for order status transitions, cash/position accounting,
  rejection, cancellation, partial fills, and reconciliation.
- Does not change live execution, backtest behavior, fixed benchmark output, or
  OpenSpec requirements for the existing pre-trade risk gate.
