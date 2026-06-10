## ADDED Requirements

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
