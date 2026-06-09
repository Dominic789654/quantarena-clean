## Context

The run `reports/multi_personality/20260609_065805_656440_03a48f06` showed two consistency failures:

- `fundamental_value` and `behavioral_momentum` produced trades, but their `broker_audit.jsonl` files were empty.
- Shared phase-1 orchestration calls the base `_generate_llm_decisions_with_precollected_signals` for smart-priority engines, bypassing specialized `_generate_llm_decisions` implementations in `FundamentalValueBacktestEngine` and `BehavioralMomentumBacktestEngine`.

The existing paper broker execution helpers already create audit events when BUY/SELL orders route through `_execute_buy`, `_execute_sell`, or target-weight conversion. The gap is the shared smart-priority path, which applies workflow decisions directly.

## Goals / Non-Goals

**Goals:**
- Preserve shared analyst-signal reuse in multi-personality mode.
- Let specialized engines consume pre-collected signals through their own logic.
- Ensure every backtest BUY/SELL that changes portfolio state has a corresponding audit event.
- Add regression coverage and an artifact-review checklist item for this class of bug.

**Non-Goals:**
- Do not change the public CLI for backtest execution.
- Do not redesign the portfolio allocator or paper broker data model.
- Do not make live trading changes.

## Decisions

1. Add a pre-collected signal hook at the engine level.

   The base engine will keep `_generate_llm_decisions_with_precollected_signals`, while specialized engines that need custom behavior override it. This keeps orchestration generic and avoids hard-coding personality-specific branches in `MultiPersonalityBacktest`.

2. Route direct LLM workflow decisions through order execution helpers.

   The base smart-priority path will convert workflow `BacktestDecision` objects into unapplied decisions and let `_execute_day_with_decisions` call `_execute_buy` / `_execute_sell`. This preserves risk validation, paper broker state transitions, trade recording, and audit event generation. Target-weight paths that already mutate the portfolio will continue returning `_applied=True`.

3. Preserve report and metrics shape.

   Existing `trades.csv`, `equity_curve.csv`, and metrics fields stay compatible. The expected behavioral change is that previously empty audit files now contain events for any executed trades, and specialized metrics reflect the intended execution path.

4. Record artifact-review checks in OpenSpec tasks.

   The post-run review will include trade/audit row-count sanity checks and specialized metric checks. This is a lightweight guardrail that catches execution-path regressions not visible in final return tables.

## Risks / Trade-offs

- [Risk] Changing `_applied` semantics for workflow decisions may double-execute if a caller also mutates the portfolio before returning decisions. → Mitigation: only direct workflow decision paths return `_applied=False`; target-weight conversion remains `_applied=True`, and tests will check trade counts and audit counts.
- [Risk] Specialized engines may recompute analyst signals if they only support the old `_generate_llm_decisions` method. → Mitigation: add explicit precollected-signal overrides for the two affected specialized engines.
- [Risk] A five-day backtest is too short for some annualized metrics. → Mitigation: tests focus on execution consistency and artifact integrity, not ranking quality.

## Migration Plan

No migration is required. New reports will include audit rows for shared smart-priority executions. Existing historical reports remain unchanged.

## Open Questions

None.
