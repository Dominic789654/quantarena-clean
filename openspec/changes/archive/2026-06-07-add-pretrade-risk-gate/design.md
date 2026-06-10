## Context

QuantArena currently turns LLM portfolio decisions into simulated portfolio mutations inside backtest and DeepFund workflows. The project has no broker interface yet, so the next safe step toward real-market operation is not broker submission; it is a deterministic pre-trade boundary that can be reused by paper and live execution later.

## Goals / Non-Goals

**Goals:**
- Represent a proposed executable order as a broker-neutral `OrderIntent`.
- Validate a DeepFund `Decision` against deterministic account, position, market-session, notional, concentration, and price-collar constraints.
- Return machine-readable rejection or adjustment reasons without relying on LLM prompt compliance.
- Keep the implementation importable by existing tests without requiring broker credentials or external services.

**Non-Goals:**
- Submit orders to a broker or exchange.
- Replace existing backtest accounting in this change.
- Add live market calendars or broker reconciliation in this change.
- Change model prompts or strategy behavior.

## Decisions

- Add a top-level `trading` package rather than placing live-safety primitives under `backtest`.
  - Rationale: `backtest/execution.py` is simulation accounting; live-oriented order/risk objects need a neutral boundary that can serve backtest, paper, and future broker paths.
  - Alternative considered: extend `backtest/execution.py`; rejected because it would further blur simulated fills and real order validation.

- Convert `Decision` to `OrderIntent` only after pre-trade validation.
  - Rationale: LLM output remains advisory. The risk gate owns executable share quantity, price checks, and rejection reasons.
  - Alternative considered: clamp directly in `portfolio_manager.py`; rejected because live safety should be centralized and testable independently of LLM/database code.

- Keep price protection explicit via optional limit-price bounds.
  - Rationale: the current decision has only one `price` field. A future broker adapter can map validated intents to market or limit orders, but this change only enforces whether the decision price is within a configured collar around the latest quote.

- Use pure dataclasses and enums.
  - Rationale: no new dependency, cheap construction, and easy unit testing. Existing Pydantic `Decision` objects can be accepted structurally by reading `action`, `shares`, `price`, and `justification`.

## Risks / Trade-offs

- [Risk] Without a full exchange calendar, `market_open` is caller-provided and can be wrong. → Mitigation: default configuration rejects trading when market status is not explicitly open.
- [Risk] The gate does not know broker-specific lot sizes, tick sizes, settlement, or margin. → Mitigation: keep these as future config extensions and reject short/insufficient-position orders now.
- [Risk] Existing backtests do not automatically use the new gate. → Mitigation: this change establishes the boundary and tests it; integration into backtest/live orchestration can follow as a separate OpenSpec change.
