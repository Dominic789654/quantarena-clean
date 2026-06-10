## Context

The repository already has broker-neutral account/order/fill/quote models, a deterministic paper broker, a persistent paper portfolio command interface, and backtest audit trails. The missing piece is a safe live-market boundary: tools should be able to inspect broker state, but this codebase should not gain live order placement until that capability is designed separately.

## Goals / Non-Goals

**Goals:**
- Provide a live read-only broker adapter surface for account, positions, orders, and quotes.
- Provide deterministic local testing through a snapshot-backed adapter without network or credentials.
- Expose read-only live inspection through `quantarena live` JSON CLI commands.
- Make mutating broker operations fail explicitly and consistently.

**Non-Goals:**
- No live order submission, cancellation, fills, or trading workflow integration.
- No dependency on a specific external broker SDK in this change.
- No credential storage or broker OAuth/session management.

## Decisions

1. Introduce `trading.live_readonly` as a separate module.
   - Rationale: keeping live read-only code separate from `PaperBroker` avoids accidental reuse of mutating paper methods.
   - Alternative considered: extend `PaperPortfolioManager`; rejected because paper commands intentionally include mutating operations.

2. Implement a snapshot-backed provider first.
   - Rationale: tests and local smoke checks need deterministic input and must not require live credentials. The snapshot provider also fixes the JSON contract expected from future real providers.
   - Alternative considered: integrate one real broker immediately; rejected because no broker choice or credential flow has been specified.

3. Use JSON-ready command results mirroring paper CLI shape.
   - Rationale: `ok`, `command`, `result`, and `error` are already familiar in `quantarena paper`, so downstream tooling can consume both consistently.

4. Reject mutations at the adapter layer.
   - Rationale: absence of CLI subcommands is not enough; programmatic access should also fail with a read-only error if a caller tries to submit, fill, or cancel.

## Risks / Trade-offs

- Snapshot provider is not a real broker integration → Mitigation: name it explicitly as a provider and keep the provider registry open for later real adapters.
- Future broker payloads may differ by provider → Mitigation: normalize all provider output to existing broker-neutral account, position, order, and quote payload fields.
- Users may expect `live` to trade → Mitigation: no mutating CLI is added and adapter mutation methods raise a specific read-only error.

## Migration Plan

Additive only. Existing paper, backtest, and provider smoke commands remain unchanged. Rollback is removing the new `live` CLI branch and `trading.live_readonly` module.

## Open Questions

- Which real broker provider should be implemented first once credentials and market scope are chosen?
- Should future live read-only snapshots be persisted for reconciliation history, or only printed on demand?
