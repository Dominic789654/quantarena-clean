## ADDED Requirements

### Requirement: Decision Validation Before Order Intent
The system SHALL validate a model trading decision with deterministic pre-trade checks before producing an executable order intent.

#### Scenario: Hold decision produces no order
- **WHEN** the risk gate receives a HOLD decision
- **THEN** the validation result SHALL be approved with no order intent.

#### Scenario: Invalid decision is rejected
- **WHEN** the risk gate receives a BUY or SELL decision with non-positive shares or non-positive price
- **THEN** the validation result SHALL be rejected with a machine-readable reason.

### Requirement: Cash And Position Enforcement
The system SHALL enforce available cash and held position limits without relying on model-provided reasoning.

#### Scenario: Buy exceeds available cash
- **WHEN** a BUY decision's notional value exceeds available cash
- **THEN** the validation result SHALL reduce the order to the maximum affordable whole-share quantity or reject it if no share is affordable.

#### Scenario: Sell exceeds held shares
- **WHEN** a SELL decision requests more shares than the current position holds
- **THEN** the validation result SHALL reduce the order to the held share quantity or reject it if no shares are held.

### Requirement: Configurable Hard Risk Limits
The system SHALL enforce configured hard limits for order notional, position concentration, price collars, shorting, and market session state.

#### Scenario: Order notional exceeds maximum
- **WHEN** a BUY or SELL decision's notional value exceeds the configured maximum order notional
- **THEN** the validation result SHALL reduce the order to the maximum allowed whole-share quantity or reject it if no share is allowed.

#### Scenario: Buy breaches concentration limit
- **WHEN** a BUY decision would make the symbol value exceed the configured maximum position weight
- **THEN** the validation result SHALL reduce the order to the maximum allowed whole-share quantity or reject it if no share is allowed.

#### Scenario: Market is closed
- **WHEN** the risk gate is configured to require an open market and the provided market state is closed
- **THEN** the validation result SHALL be rejected.

#### Scenario: Price exceeds collar
- **WHEN** a decision price is outside the configured basis-point collar around the latest quote
- **THEN** the validation result SHALL be rejected.

### Requirement: Broker-Neutral Order Intent
The system SHALL represent approved BUY and SELL validations as broker-neutral order intents.

#### Scenario: Approved buy creates order intent
- **WHEN** a BUY decision passes all pre-trade checks
- **THEN** the validation result SHALL include an order intent containing symbol, side, shares, limit price, source decision details, and risk adjustments.

#### Scenario: Approved sell creates order intent
- **WHEN** a SELL decision passes all pre-trade checks
- **THEN** the validation result SHALL include an order intent containing symbol, side, shares, limit price, source decision details, and risk adjustments.
