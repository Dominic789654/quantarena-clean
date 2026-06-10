## Context

Paper broker execution is now part of the backtest path, and fixed benchmark runs show cash and positions are correct. The remaining gap is observability: reports show trades and snapshots, but not the full execution lineage from model decision through risk validation, broker order, fill, and final portfolio mutation.

## Goals / Non-Goals

**Goals:**
- Record one audit event per execution attempt, including successful fills and rejected attempts.
- Keep order and fill identifiers monotonic within a backtest run so audit events are traceable.
- Export a stable `broker_audit.jsonl` artifact from normal report generation.
- Preserve all existing report files and their schemas.

**Non-Goals:**
- No live broker integration.
- No change to trade CSV schema.
- No database-backed audit store.
- No UI changes in the HTML dashboard.

## Decisions

- Store audit events as plain JSON-ready dictionaries.
  - Rationale: the report writer can emit JSONL directly, and tests can assert exact fields without adding a new serialization dependency.
  - Alternative considered: a dataclass-only model. That is useful for structure but still needs a JSON boundary; plain dicts keep this change small.

- Maintain paper broker order/fill sequences in hidden `current_portfolio` keys during backtest execution.
  - Rationale: execution helpers currently build a short-lived `PaperBroker` per execution; hidden sequence keys preserve unique IDs without replacing the broader portfolio data model.
  - Alternative considered: a long-lived broker instance in `BacktestEngine`. Cleaner long-term, but larger blast radius for current report and metrics code.

- Pass an optional audit list into execution helpers.
  - Rationale: tests can call helpers without audit, while `BacktestEngine` can collect events for report generation.

- Export JSONL from `BacktestReportGenerator.generate_full_report`.
  - Rationale: this is the single place that already owns report directory artifact paths.

## Risks / Trade-offs

- [Risk] Hidden sequence keys in `current_portfolio` could leak into calculations. -> Mitigation: existing calculations read `positions` and `cashflow`; tests cover report and execution behavior.
- [Risk] JSONL audit could grow large for long runs. -> Mitigation: JSONL is append-friendly and streaming-readable; no dashboard parsing is added.
- [Risk] Rejected attempts may have no order/fill IDs. -> Mitigation: audit fields allow null order/fill IDs while preserving rejection source and reasons.

## Migration Plan

- Existing reports remain valid.
- New reports include `broker_audit.jsonl`.
- Existing artifact loaders may treat audit as optional until downstream tooling adopts it.

## Open Questions

- Whether to surface audit events in the HTML dashboard is intentionally deferred to a later change.
