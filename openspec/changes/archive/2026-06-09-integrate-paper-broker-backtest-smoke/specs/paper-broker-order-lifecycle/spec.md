## ADDED Requirements

### Requirement: Preserve Persistent Paper Broker ID Sequences
The system SHALL preserve monotonic paper order and fill ID sequences across persisted paper portfolio state reloads.

#### Scenario: Submit order after reload
- **WHEN** a paper portfolio state contains an existing order and a later command reloads that state before submitting another order
- **THEN** the new order SHALL receive an ID greater than all existing paper order IDs and SHALL NOT collide with stored orders.

#### Scenario: Fill order after reload
- **WHEN** a paper portfolio state contains existing fill records and a later command reloads that state before applying another fill
- **THEN** the new fill SHALL receive an ID greater than all existing paper fill IDs and SHALL NOT collide with stored fills.

#### Scenario: Legacy state lacks sequence fields
- **WHEN** a persisted paper portfolio state does not contain explicit next ID sequence fields
- **THEN** the loader SHALL derive the next order and fill IDs from existing order and fill records.
