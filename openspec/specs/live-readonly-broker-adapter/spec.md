# live-readonly-broker-adapter Specification

## Purpose
Define the safe live broker inspection boundary: read-only account, position, order, and quote snapshots with explicit rejection of all mutating broker operations.
## Requirements
### Requirement: Configure Live Readonly Broker Adapter
The system SHALL configure a live read-only broker adapter without enabling live trading.

#### Scenario: Snapshot provider configured
- **WHEN** callers configure the live read-only adapter with provider `snapshot` and a readable snapshot path
- **THEN** the adapter SHALL load broker-neutral account, position, order, and quote payloads from that snapshot.

#### Scenario: Missing provider configuration
- **WHEN** callers request a live read-only adapter without the required provider configuration
- **THEN** the system SHALL fail with a machine-readable error and SHALL NOT attempt any broker mutation.

### Requirement: Read Live Broker Snapshots
The system SHALL expose live broker account, position, order, and quote snapshots through read-only methods.

#### Scenario: Account snapshot
- **WHEN** callers request the live account snapshot
- **THEN** the adapter SHALL return a JSON-serializable account payload containing cash, total value, buying power, and currency when available.

#### Scenario: Position snapshot
- **WHEN** callers request live positions
- **THEN** the adapter SHALL return JSON-serializable position payloads containing symbol, shares, market value, and last price when available.

#### Scenario: Order snapshot
- **WHEN** callers request live orders with optional status or symbol filters
- **THEN** the adapter SHALL return only matching JSON-serializable order payloads.

#### Scenario: Quote snapshot
- **WHEN** callers request live quotes for one or more symbols
- **THEN** the adapter SHALL return JSON-serializable quote payloads for the requested symbols that are available from the provider.

### Requirement: Prevent Live Broker Mutations
The system SHALL reject live broker order submission, order fill, order cancellation, and other mutating operations from the read-only adapter.

#### Scenario: Submit order rejected
- **WHEN** a caller attempts to submit an order through the live read-only adapter
- **THEN** the adapter SHALL reject the request with a read-only error and SHALL NOT send any broker order.

#### Scenario: Cancel order rejected
- **WHEN** a caller attempts to cancel an order through the live read-only adapter
- **THEN** the adapter SHALL reject the request with a read-only error and SHALL NOT send any broker cancellation.

### Requirement: Provide Live Readonly CLI
The system SHALL expose live read-only inspection through `quantarena live` CLI commands.

#### Scenario: CLI JSON output
- **WHEN** a `quantarena live` read command completes
- **THEN** it SHALL print a JSON payload containing `ok`, `command`, and command result fields.

#### Scenario: CLI smoke succeeds
- **WHEN** the live read-only smoke command is invoked with a readable snapshot provider
- **THEN** it SHALL query account, positions, orders, and quotes and return `ok=true` with machine-readable step results.

#### Scenario: CLI has no mutating commands
- **WHEN** users inspect the `quantarena live` CLI surface
- **THEN** it SHALL NOT expose order submit, fill, cancel, or other mutating subcommands.

### Requirement: Report Live Readonly Health Metadata
The system SHALL report machine-readable health metadata for the live read-only adapter without enabling broker mutations.

#### Scenario: Smoke health includes readonly metadata
- **WHEN** the live read-only smoke command completes
- **THEN** the result SHALL include provider metadata, read-only status, mutation-disabled status, and snapshot path when available.

#### Scenario: Smoke health reports per-read checks
- **WHEN** smoke checks account, positions, orders, and quotes
- **THEN** each step SHALL report the command name, ok status, and item count where the read result is countable.

#### Scenario: Smoke health reports read failure
- **WHEN** any smoke read step fails
- **THEN** the smoke result SHALL set `ok=false`, identify the failed command, include the error message for that step, and SHALL NOT attempt any broker mutation.

### Requirement: Expose Live Readonly Capability Marker
The system SHALL expose a machine-readable capability marker proving that live broker access is read-only.

#### Scenario: Manager reports readonly capabilities
- **WHEN** callers request live read-only capabilities from the manager
- **THEN** the manager SHALL report `readonly=true`, `mutation_allowed=false`, provider identity, and available read operations.

#### Scenario: Manager exposes no mutation facade
- **WHEN** callers inspect the live read-only manager API
- **THEN** it SHALL NOT expose submit, fill, cancel, or other order mutation facade methods.

