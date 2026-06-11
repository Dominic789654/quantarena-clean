## 1. Provider Contract Core

- [x] 1.1 Add live read-only provider error categories for credentials, rate limits, provider errors, and schema errors.
- [x] 1.2 Add provider contract validation for account, positions, orders, and quotes.

## 2. CLI and Exports

- [x] 2.1 Add a `quantarena live contract` read-only command.
- [x] 2.2 Export the provider contract result and error primitives from the trading package.

## 3. Tests and Validation

- [x] 3.1 Add broker tests for passing contract validation, schema failures, credential failures, and rate-limit failures.
- [x] 3.2 Add CLI tests for `quantarena live contract` success and safe failure output.
- [x] 3.3 Validate the OpenSpec change strictly and run targeted test coverage.
