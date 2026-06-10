## 1. Persistent paper broker IDs

- [x] 1.1 Add configurable next order/fill sequence support to `PaperBroker`.
- [x] 1.2 Persist sequence fields in paper portfolio state and derive them from legacy states when missing.
- [x] 1.3 Add tests for reload-safe order and fill ID continuation.

## 2. Backtest execution through paper broker

- [x] 2.1 Add execution helper logic that builds a paper broker from the current backtest portfolio and quotes.
- [x] 2.2 Route direct BUY/SELL execution helpers through paper broker submit/fill and sync back to the existing portfolio dictionary.
- [x] 2.3 Route target-allocation BUY/SELL helper execution through the same broker lifecycle.
- [x] 2.4 Add or update execution-helper tests to assert paper broker routing preserves accounting and rejection behavior.

## 3. Paper portfolio smoke command

- [x] 3.1 Add a deterministic smoke method to `PaperPortfolioManager`.
- [x] 3.2 Add `quantarena paper smoke` CLI support.
- [x] 3.3 Add manager and CLI tests for successful smoke output and non-network behavior.

## 4. Validation

- [x] 4.1 Run focused pytest coverage for paper broker, paper portfolio commands, execution helpers, CLI, and fixed benchmark runner.
- [x] 4.2 Run `quantarena paper smoke` and `quantarena smoke --json`.
- [x] 4.3 Run OpenSpec validation and archive the change.
