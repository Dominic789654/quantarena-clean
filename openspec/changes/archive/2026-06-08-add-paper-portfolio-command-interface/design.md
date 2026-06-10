## Context

`PaperBroker` now models local order lifecycle and accounting, but it is an
in-memory object. To exercise the interface like a local simulated portfolio
manager, callers need a command facade and CLI that persist state across process
invocations.

## Goals / Non-Goals

**Goals:**
- Provide a persistent local paper state file.
- Add command handling for account, positions, orders, quote set/list, order
  submit/fill/cancel, and reconciliation.
- Expose commands through `quantarena paper ...`.
- Return JSON-serializable payloads suitable for scripts and future agent
  integration.

**Non-Goals:**
- Do not connect to a live broker.
- Do not expose an HTTP server.
- Do not integrate the command interface into backtest execution yet.
- Do not add concurrency locking beyond simple atomic file replacement.

## Decisions

- Store state as JSON under `data/paper_portfolio/state.json` by default.
  - Rationale: easy to inspect, ignored by git through `data/`, and enough for a
    local paper interface.

- Rehydrate `PaperBroker` from state for every command and save it after mutating
  commands.
  - Rationale: keeps commands stateless at the process level and avoids a daemon.

- Use `quantarena paper` subcommands rather than a separate script.
  - Rationale: this is a stable engineering utility like report visualizer and
    provider smoke checks.

- Return JSON by default for paper commands.
  - Rationale: the interface is meant to be consumed by local tools and agents;
    human formatting can be added later.

## Risks / Trade-offs

- [Risk] Concurrent commands can race on the state file. -> Mitigation: use a
  single local command process for now; a future daemon or file lock can be added
  if needed.

- [Risk] JSON state is not suitable for long-term audit. -> Mitigation: this is
  a bridge layer for local simulation; durable audit storage belongs in a later
  live/paper trading system change.

- [Risk] Command interface can submit orders that did not pass risk gate if used
  directly. -> Mitigation: mark direct CLI orders as manual paper commands in
  metadata; strategy integration should still call `PreTradeRiskEngine` first.
