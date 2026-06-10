## Why

QuantArena now has deterministic paper brokerage and auditability, but the next step toward real-market integration needs a safe way to inspect live broker state without enabling live trading. A read-only adapter lets local tooling compare real account, position, order, and quote snapshots while preserving a hard no-order-submission boundary.

## What Changes

- Add a live read-only broker adapter abstraction that exposes account, positions, orders, and quotes through existing broker-neutral payload shapes.
- Add a deterministic snapshot-backed adapter implementation for local testing and development without live credentials.
- Add CLI commands under `quantarena live` for account, positions, orders, quotes, and smoke checks.
- Explicitly reject live order submission, fill, cancel, or other mutating operations from the read-only adapter surface.
- No breaking changes.

## Capabilities

### New Capabilities
- `live-readonly-broker-adapter`: Defines safe read-only live broker access, provider configuration, JSON command output, and hard rejection of mutating operations.

### Modified Capabilities
- None.

## Impact

- Adds trading-domain live-readonly adapter models and a snapshot-backed provider.
- Adds QuantArena CLI read-only live commands.
- Adds focused tests for adapter behavior, CLI payloads, and mutation rejection.
- Does not add live trading or broker order placement.
