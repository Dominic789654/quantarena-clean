## Context

The repository has `OrderIntent` and `PreTradeRiskEngine`, which define the
deterministic boundary between LLM decisions and executable orders. The next
layer should simulate broker behavior before real brokerage APIs are introduced:
order ids, status transitions, fills, cash and position accounting, and
reconciliation.

## Goals / Non-Goals

**Goals:**
- Add broker-neutral data models for accounts, positions, quotes, orders, and
  fills.
- Add a local paper broker that accepts `OrderIntent` and manages an order
  lifecycle.
- Update account state only through fill application.
- Provide reconciliation helpers to compare expected local state with broker
  state.
- Keep the implementation deterministic and testable without network access.

**Non-Goals:**
- Do not integrate paper broker into the existing backtest engine in this change.
- Do not add a live broker adapter, broker credentials, or real order submission.
- Do not add persistence beyond an in-memory order store.
- Do not model commissions, slippage, bid/ask, market sessions, or advanced
  order types yet.

## Decisions

- Use dataclasses and enums in `trading/broker.py`.
  - Rationale: this matches the existing `trading/order.py` style and keeps the
    broker contract dependency-light.

- Implement `InMemoryOrderStore` separately from `PaperBroker`.
  - Rationale: order storage can later be swapped for SQLite or a broker-backed
    store without changing paper broker accounting behavior.

- Make submitted paper orders accepted immediately unless the intent is invalid.
  - Rationale: this keeps the first lifecycle deterministic while preserving both
    submitted and accepted status concepts in the model.

- Fill orders explicitly via `fill_order(...)` rather than automatically at
  submit time.
  - Rationale: explicit fills let tests and future execution models simulate
    full fills, partial fills, rejections, and cancellations.

- Enforce no negative cash and no short positions by default.
  - Rationale: this matches the current risk-gate defaults and prevents paper
    state from masking execution mistakes.

## Risks / Trade-offs

- [Risk] In-memory orders disappear between processes. -> Mitigation: this is
  intentional for the first paper broker layer; persistence can be a later
  change once the lifecycle contract is stable.

- [Risk] Fill prices are caller-provided and may not reflect realistic execution.
  -> Mitigation: paper broker is an accounting and lifecycle layer; slippage and
  market simulation belong in a later execution model.

- [Risk] Not integrating into backtest means the new layer is not yet exercised
  by fixed benchmarks. -> Mitigation: this change establishes the paper broker
  contract first; a later change can route backtest or paper trading through it.
