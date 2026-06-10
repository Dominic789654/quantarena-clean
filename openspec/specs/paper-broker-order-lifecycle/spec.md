# paper-broker-order-lifecycle Specification

## Purpose
TBD - created by archiving change add-paper-broker-order-lifecycle. Update Purpose after archive.
## Requirements
### Requirement: Submit Risk-Approved Paper Orders
The system SHALL submit only broker-neutral `OrderIntent` values to the paper
broker and SHALL create broker order records with machine-readable status.

#### Scenario: Submit valid buy intent
- **WHEN** a risk-approved BUY `OrderIntent` is submitted to the paper broker
- **THEN** the broker SHALL create an order with status `submitted` or
  `accepted`, preserve the requested symbol, side, shares, and limit price, and
  assign a stable order id.

#### Scenario: Reject invalid intent
- **WHEN** an order intent has non-positive shares or non-positive limit price
- **THEN** the broker SHALL create a rejected order with a rejection reason and
  SHALL NOT update cash or positions.

### Requirement: Fill Paper Orders
The system SHALL update paper account cash and positions from fills rather than
direct strategy mutation.

#### Scenario: Buy order fills
- **WHEN** an accepted BUY order is filled for a positive quantity and fill price
- **THEN** the broker SHALL decrease cash by fill quantity times fill price,
  increase the symbol position by the filled quantity, append a fill record, and
  mark the order `filled` when the full order quantity is filled.

#### Scenario: Sell order fills
- **WHEN** an accepted SELL order is filled for a positive quantity and fill price
- **THEN** the broker SHALL increase cash by fill quantity times fill price,
  decrease the symbol position by the filled quantity, append a fill record, and
  mark the order `filled` when the full order quantity is filled.

#### Scenario: Partial fill remains open
- **WHEN** a fill quantity is less than the remaining order quantity
- **THEN** the broker SHALL mark the order `partial_filled` and preserve the
  remaining quantity for later fills or cancellation.

### Requirement: Enforce Paper Broker Accounting Limits
The system SHALL prevent paper fills that would create impossible account states
under the default no-short, no-negative-cash paper broker configuration.

#### Scenario: Buy would exceed cash
- **WHEN** a BUY fill would require more cash than the paper account has
- **THEN** the broker SHALL reject the fill and leave account cash, positions,
  and order filled quantity unchanged.

#### Scenario: Sell would exceed position
- **WHEN** a SELL fill would sell more shares than the current paper position
- **THEN** the broker SHALL reject the fill and leave account cash, positions,
  and order filled quantity unchanged.

### Requirement: Cancel Paper Orders
The system SHALL support cancellation of paper orders that are still open.

#### Scenario: Cancel open order
- **WHEN** a submitted, accepted, or partially filled order is cancelled
- **THEN** the broker SHALL mark the order `cancelled` and prevent future fills
  against that order.

#### Scenario: Cancel terminal order
- **WHEN** a filled, rejected, or already cancelled order is cancelled
- **THEN** the broker SHALL leave the order in its terminal status and report
  that cancellation was not applied.

### Requirement: Snapshot And Reconcile Paper Broker State
The system SHALL expose paper broker account, position, order, quote, and
reconciliation snapshots for downstream paper/live integration.

#### Scenario: Account and position snapshots
- **WHEN** callers request account and position snapshots
- **THEN** the broker SHALL return current cash, positions, open orders, and
  latest quote-derived market values without requiring external network access.

#### Scenario: Reconciliation has no differences
- **WHEN** expected local cash and positions match the paper broker state
- **THEN** reconciliation SHALL report success with no differences.

#### Scenario: Reconciliation detects differences
- **WHEN** expected local cash or positions differ from the paper broker state
- **THEN** reconciliation SHALL report failure with machine-readable difference
  records.

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
