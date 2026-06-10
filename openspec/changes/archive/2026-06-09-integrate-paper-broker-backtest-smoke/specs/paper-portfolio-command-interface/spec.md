## ADDED Requirements

### Requirement: Run Paper Portfolio Smoke Check
The system SHALL expose a deterministic paper portfolio smoke check through the local command interface and `quantarena paper` CLI.

#### Scenario: Smoke check succeeds
- **WHEN** the smoke command is invoked with a writable state path
- **THEN** it SHALL initialize a paper state, set a quote, submit an order, fill it, query account, positions, orders, and quotes, reconcile the expected state, and return `ok=true` with machine-readable step results.

#### Scenario: Smoke check uses isolated overwrite
- **WHEN** the smoke command writes to its target state path
- **THEN** it SHALL overwrite only that state path and SHALL NOT require network access or live broker credentials.

#### Scenario: CLI smoke failure
- **WHEN** any step in the paper CLI smoke check fails
- **THEN** the CLI SHALL print a JSON payload with `ok=false`, include the failing step result, and exit non-zero.
