## ADDED Requirements

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
