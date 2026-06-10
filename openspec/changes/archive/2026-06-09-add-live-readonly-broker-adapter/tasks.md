## 1. Readonly Adapter

- [x] 1.1 Add live readonly command result, configuration, and read-only error types.
- [x] 1.2 Implement snapshot-backed account, position, order, and quote reads.
- [x] 1.3 Reject submit, fill, and cancel attempts at the adapter layer.

## 2. CLI Integration

- [x] 2.1 Add `quantarena live` parser commands for account, positions, orders, quotes, and smoke.
- [x] 2.2 Add CLI dispatch that returns paper-style JSON payloads and clean non-zero failures.
- [x] 2.3 Export live readonly adapter types from the trading package.

## 3. Tests and Validation

- [x] 3.1 Add adapter tests for snapshot reads, filters, smoke, and mutation rejection.
- [x] 3.2 Add CLI tests for parser surface, JSON output, smoke, and absence of mutating commands.
- [x] 3.3 Run focused pytest, CLI smoke, and OpenSpec validation.
- [x] 3.4 Archive the OpenSpec change.
