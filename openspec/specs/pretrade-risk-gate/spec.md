# pretrade-risk-gate Specification

## Purpose
TBD - created by archiving change add-pretrade-risk-gate. Update Purpose after archive.
## Requirements
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

### Requirement: Backtest Execution Uses Risk Gate
The system SHALL route simulated backtest BUY and SELL execution through the deterministic pre-trade risk gate before mutating simulated portfolio state.

#### Scenario: Plain buy execution is validated
- **WHEN** a backtest helper receives a BUY order with positive shares and price
- **THEN** the helper SHALL validate the decision through the pre-trade risk gate before reducing cash, increasing shares, or recording a trade.

#### Scenario: Plain sell execution is validated
- **WHEN** a backtest helper receives a SELL order with positive shares and price
- **THEN** the helper SHALL validate the decision through the pre-trade risk gate before increasing cash, reducing shares, or recording a trade.

### Requirement: Target Allocation Conversion Uses Risk Gate
The system SHALL route target-weight trade conversion through the deterministic pre-trade risk gate before applying simulated target allocation trades.

#### Scenario: Target buy is cash limited by risk gate
- **WHEN** a target allocation requests more buy shares than available cash allows
- **THEN** the simulated trade SHALL use the risk-gate adjusted share quantity and expose the cash-limit reason on the returned decision.

#### Scenario: Target sell is position limited by risk gate
- **WHEN** a target allocation requests more sell shares than the current position holds
- **THEN** the simulated trade SHALL use the risk-gate adjusted share quantity and expose the position-limit reason on the returned decision.

#### Scenario: Invalid target trade is rejected
- **WHEN** a target allocation would require a BUY or SELL at a non-positive price
- **THEN** the returned decision SHALL be HOLD with machine-readable risk rejection reasons and no simulated trade SHALL be recorded.
