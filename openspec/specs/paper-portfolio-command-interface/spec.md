# paper-portfolio-command-interface Specification

## Purpose
TBD - created by archiving change add-paper-portfolio-command-interface. Update Purpose after archive.
## Requirements
### Requirement: Persist Paper Portfolio State
The system SHALL persist simulated paper portfolio state in a local JSON state
file containing cash, positions, quotes, orders, and fills.

#### Scenario: Initialize state
- **WHEN** the paper portfolio interface is initialized with an initial cash
  value and state path
- **THEN** it SHALL create or replace the state file with that cash value,
  empty positions, empty quotes, empty orders, and no fills.

#### Scenario: Reload state
- **WHEN** a later command uses the same state path
- **THEN** it SHALL load the previous paper account, positions, quotes, orders,
  and fills before applying the command.

### Requirement: Operate Paper Portfolio Commands
The system SHALL expose local paper portfolio commands for account, position,
order, quote, fill, cancel, and reconciliation operations.

#### Scenario: Query account and positions
- **WHEN** account or positions commands are invoked
- **THEN** the interface SHALL return JSON-serializable current account and
  position snapshots.

#### Scenario: Set quote
- **WHEN** a quote set command is invoked with a symbol and price
- **THEN** the interface SHALL persist the quote and use it for later market
  value snapshots.

#### Scenario: Submit order
- **WHEN** an order submit command is invoked with symbol, side, shares, and
  limit price
- **THEN** the interface SHALL submit an `OrderIntent` to the paper broker,
  persist the resulting broker order, and return the order payload.

#### Scenario: Fill order
- **WHEN** an order fill command is invoked for an open paper order
- **THEN** the interface SHALL apply the fill through the paper broker, persist
  updated cash, positions, fills, and order status, and return the fill result.

#### Scenario: Cancel order
- **WHEN** an order cancel command is invoked for an open paper order
- **THEN** the interface SHALL cancel the order through the paper broker,
  persist the terminal order status, and return the cancellation result.

#### Scenario: Reconcile state
- **WHEN** a reconcile command is invoked with expected cash and expected
  positions
- **THEN** the interface SHALL compare expected local state to the paper broker
  state and return machine-readable differences.

### Requirement: Provide Paper Portfolio CLI
The system SHALL expose the paper portfolio command interface through
`quantarena paper` CLI subcommands.

#### Scenario: CLI JSON output
- **WHEN** a `quantarena paper` subcommand completes
- **THEN** it SHALL print a JSON payload containing `ok`, `command`, and command
  result fields.

#### Scenario: CLI state path override
- **WHEN** a `quantarena paper` subcommand is invoked with `--state`
- **THEN** it SHALL use that state path instead of the default paper portfolio
  state path.

#### Scenario: CLI command failure
- **WHEN** a `quantarena paper` subcommand fails validation or broker execution
- **THEN** it SHALL print a JSON payload with `ok=false` and exit non-zero.

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
