## ADDED Requirements

### Requirement: Validate Live Readonly Provider Contract
The system SHALL validate that every live read-only provider implements the broker-neutral read contract before it is treated as a real broker adapter.

#### Scenario: Provider contract succeeds
- **WHEN** callers run the provider contract check against a configured provider with valid account, position, order, and quote reads
- **THEN** the result SHALL report `ok=true`, provider identity, read-only status, mutation-disabled status, and per-read schema checks.

#### Scenario: Provider contract validates normalized fields
- **WHEN** the provider contract check inspects account, position, order, and quote payloads
- **THEN** it SHALL require broker-neutral JSON-serializable fields for account cash, total value, buying power, currency; position symbol, shares, market value, last price; order id, status, symbol, side, shares, filled and remaining quantities; and quote symbol and price.

#### Scenario: Provider contract reports schema failure
- **WHEN** a provider returns a payload that does not satisfy the normalized read contract
- **THEN** the contract result SHALL report `ok=false`, category `schema_error`, the failed read command, and a machine-readable issue list.

#### Scenario: Provider contract reports credential failure
- **WHEN** a provider cannot read because required credentials are missing or empty
- **THEN** the contract result SHALL report `ok=false`, category `credential_missing`, and SHALL NOT attempt any broker mutation.

#### Scenario: Provider contract reports rate limit failure
- **WHEN** a provider read is rejected by a provider rate limit
- **THEN** the contract result SHALL report `ok=false`, category `rate_limited`, the failed read command, and SHALL NOT attempt any broker mutation.

### Requirement: Provide Live Readonly Provider Contract CLI
The system SHALL expose provider contract validation through the read-only `quantarena live` CLI surface.

#### Scenario: CLI contract succeeds
- **WHEN** `quantarena live contract` is invoked with a provider that satisfies the live read-only provider contract
- **THEN** it SHALL print JSON containing `ok=true`, `command=contract`, provider metadata, and per-read contract checks.

#### Scenario: CLI contract fails safely
- **WHEN** `quantarena live contract` is invoked with a provider that fails configuration, credentials, rate-limit, or schema validation
- **THEN** it SHALL print JSON containing `ok=false`, `command=contract`, a stable error category when available, and SHALL NOT expose submit, fill, cancel, or other mutating subcommands.
