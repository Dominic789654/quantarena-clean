## Context

QuantArena now has broker-neutral order intents, a pre-trade risk gate, a local `PaperBroker`, and a persistent paper portfolio command interface. The remaining gap is that backtest execution still directly mutates `current_portfolio` dictionaries, while the paper portfolio state loader recreates `PaperBroker` counters from their defaults. That makes the paper broker less useful as the shared execution seam for backtests, local paper state, and future live read-only adapters.

## Goals / Non-Goals

**Goals:**
- Make persisted paper portfolios safe to use across multiple CLI invocations by preserving order and fill ID sequences.
- Route backtest execution through the same `PaperBroker` lifecycle used by local paper commands.
- Keep existing backtest reports, metrics, trade CSVs, and fixed benchmark CLI behavior stable.
- Add a deterministic paper smoke command for fast local verification.

**Non-Goals:**
- No live trading or live broker order submission.
- No change to LLM decision generation.
- No change to generated report schemas.
- No new database, server, or network dependency.

## Decisions

- Store paper broker sequences in memory as configurable `next_order_sequence` and `next_fill_sequence` values.
  - Rationale: this keeps `PaperBroker` deterministic and avoids parsing IDs on every submit/fill.
  - Alternative considered: derive the next ID from stored orders on every operation. That is simpler state-wise but repeatedly scans the order list and hides sequence ownership outside the broker.

- Persist explicit `next_order_sequence` and `next_fill_sequence` fields in paper portfolio state, while deriving them from legacy state when absent.
  - Rationale: new states are cheap to load, old states remain compatible.
  - Alternative considered: bump the schema version. That would require a migration for state files that can instead be handled safely by derivation.

- Add helper functions in `backtest/execution.py` that build a temporary `PaperBroker` from the existing `current_portfolio`, submit and fill one order, then sync the existing dictionary shape from the broker.
  - Rationale: this preserves the public backtest engine contract and keeps the change scoped to execution helpers.
  - Alternative considered: replace `current_portfolio` throughout `BacktestEngine` with `PaperBroker`. That is cleaner long-term but has a much larger blast radius across metrics, reports, and tests.

- Keep trade recording at the existing recorder boundary after the paper broker fill succeeds.
  - Rationale: reports and metrics already depend on that recorder shape.

- Implement paper smoke as a manager method plus CLI subcommand.
  - Rationale: tests can call the manager directly and CLI behavior remains a thin wrapper.

## Risks / Trade-offs

- [Risk] Temporary per-order paper brokers may not expose a long-lived order book during backtests. -> Mitigation: this change is about routing accounting through the paper lifecycle while preserving report contracts; persistent order history remains covered by the paper portfolio command interface.
- [Risk] Sequence derivation from malformed legacy IDs could skip unexpected records. -> Mitigation: parse only known `paper-000001` and `fill-000001` patterns and fall back to sequence 1 when none are found.
- [Risk] Backtest metrics could drift if dictionary sync changes rounding. -> Mitigation: preserve the current cashflow/positions shape and run focused execution tests plus the fixed benchmark tests.

## Migration Plan

- New paper state files include explicit sequence fields.
- Existing state files without sequence fields load normally and derive the next values from stored orders/fills.
- Rollback is straightforward because the new state fields are additive; older code ignores unknown fields if it reads only the existing keys.

## Open Questions

- None for this change. Live read-only adapters remain a separate future OpenSpec change.
