## Why

The paper broker lifecycle exists as Python primitives, but there is no local
portfolio-manager entry point that can accept commands and persist simulated
account state across invocations. A command interface lets strategies, CLI
tools, and future live adapters use the same account/order/quote operations
before any real broker integration.

## What Changes

- Add a local paper portfolio state file that persists cash, positions, quotes,
  orders, and fills.
- Add a command facade for account, positions, orders, quote set/list, order
  submit/fill/cancel, and reconciliation operations.
- Add CLI commands under `quantarena paper ...` with JSON output by default-ready
  payloads.
- Keep the interface local-only and deterministic; no live broker, network, or
  credential dependency is introduced.

## Capabilities

### New Capabilities
- `paper-portfolio-command-interface`: Local command interface and CLI for
  operating a persistent simulated paper portfolio.

### Modified Capabilities
None.

## Impact

- Adds paper portfolio state serialization and command handling under
  `trading/`.
- Extends `quantarena.cli` with a `paper` command group.
- Adds focused tests for command handling, CLI routing, persistence, and
  end-to-end simulated order lifecycle through the command interface.
