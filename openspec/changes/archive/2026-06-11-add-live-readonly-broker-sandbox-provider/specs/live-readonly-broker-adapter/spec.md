## ADDED Requirements

### Requirement: Configure Paper Sandbox Live Readonly Provider
The system SHALL support a local paper-sandbox provider for the live read-only broker adapter without enabling live trading.

#### Scenario: Paper sandbox provider configured
- **WHEN** callers configure the live read-only adapter with provider `paper_sandbox` and a readable paper portfolio state path
- **THEN** the adapter SHALL load broker-neutral account, position, order, and quote payloads from that paper state.

#### Scenario: Paper sandbox provider missing state
- **WHEN** callers configure provider `paper_sandbox` without a readable paper portfolio state path
- **THEN** the system SHALL fail with a machine-readable read-only configuration error and SHALL NOT attempt any broker mutation.

### Requirement: Read Paper Sandbox Through Live Readonly Interface
The system SHALL expose local paper-sandbox account, position, order, and quote reads through the same live read-only interface as other providers.

#### Scenario: Paper sandbox reads account and positions
- **WHEN** callers request account and positions from provider `paper_sandbox`
- **THEN** the adapter SHALL return broker-neutral JSON-serializable payloads derived from the paper state file.

#### Scenario: Paper sandbox filters orders and quotes
- **WHEN** callers request orders or quotes from provider `paper_sandbox` with optional filters
- **THEN** the adapter SHALL return only matching broker-neutral payloads from the paper state file.

#### Scenario: Paper sandbox provider satisfies contract
- **WHEN** callers run the live read-only provider contract check against provider `paper_sandbox`
- **THEN** the result SHALL report `ok=true` when the paper state contains valid broker-neutral account, position, order, and quote data.

#### Scenario: Paper sandbox live CLI does not mutate state
- **WHEN** users invoke `quantarena live` commands with provider `paper_sandbox`
- **THEN** the commands SHALL NOT initialize paper state, set quotes, submit orders, fill orders, cancel orders, or modify the paper state file.
