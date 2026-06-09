## MODIFIED Requirements

### Requirement: Record Paper Broker Execution Attempts
The system SHALL record machine-readable audit events for every paper-broker-routed backtest execution attempt, including filled orders and rejected attempts. Backtest execution paths that mutate cash or positions for BUY or SELL decisions SHALL route through paper-broker-compatible execution helpers or emit equivalent paper broker audit events.

#### Scenario: Filled execution audit
- **WHEN** a backtest BUY or SELL execution is submitted to the paper broker and filled
- **THEN** the audit event SHALL include date, symbol, side, requested shares, approved shares, limit price, order id, fill id, outcome, cash before/after, positions before/after, risk reasons, and source justification.

#### Scenario: Risk-gate rejection audit
- **WHEN** pre-trade risk validation rejects a backtest execution before broker submission
- **THEN** the audit event SHALL include date, symbol, requested side, requested shares, requested price, outcome `rejected`, rejection source `risk_gate`, and machine-readable risk reasons.

#### Scenario: Paper-broker rejection audit
- **WHEN** the paper broker rejects an order or fill
- **THEN** the audit event SHALL include outcome `rejected`, rejection source `paper_broker`, the broker rejection reason when available, and unchanged portfolio cash and positions.

#### Scenario: Shared smart-priority execution audit
- **WHEN** shared multi-personality smart-priority execution applies a BUY or SELL decision to a backtest portfolio
- **THEN** the execution SHALL produce a paper broker audit event for that decision before the daily snapshot is recorded.
