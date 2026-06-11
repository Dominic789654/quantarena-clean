## 1. Paper Sandbox Provider

- [x] 1.1 Add `paper_state_path` configuration and `paper_sandbox` provider factory support.
- [x] 1.2 Implement a read-only paper-sandbox adapter for account, positions, orders, and quotes.

## 2. CLI and Exports

- [x] 2.1 Add `quantarena live --paper-state` configuration for provider `paper_sandbox`.
- [x] 2.2 Export the paper-sandbox adapter from the trading package.

## 3. Tests and Validation

- [x] 3.1 Add broker tests for paper-sandbox reads, filtering, contract validation, missing state, and read-only mutation rejection.
- [x] 3.2 Add CLI tests proving `paper_sandbox` live commands work and do not mutate the paper state file.
- [x] 3.3 Validate the OpenSpec change strictly and run targeted test coverage.
