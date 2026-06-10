## ADDED Requirements

### Requirement: Execute Backtest Orders Through Paper Broker
The system SHALL execute backtest BUY and SELL decisions by submitting broker-neutral order intents to the local `PaperBroker`, filling accepted orders, and then synchronizing the existing backtest portfolio and report records from the broker result.

#### Scenario: Backtest buy decision fills through paper broker
- **WHEN** a backtest BUY decision passes pre-trade validation
- **THEN** the execution path SHALL submit the resulting order intent to `PaperBroker`, fill the accepted order at the backtest price, update cash and positions from the broker account, and record the trade in the existing report format.

#### Scenario: Backtest sell decision fills through paper broker
- **WHEN** a backtest SELL decision passes pre-trade validation
- **THEN** the execution path SHALL submit the resulting order intent to `PaperBroker`, fill the accepted order at the backtest price, update cash and positions from the broker account, and record the trade in the existing report format.

#### Scenario: Broker rejects fill
- **WHEN** the paper broker rejects a backtest fill because cash, position, shares, or price constraints fail
- **THEN** the execution path SHALL leave the backtest portfolio unchanged, SHALL NOT record a trade, and SHALL emit a warning describing the rejection.

### Requirement: Preserve Backtest Reporting Contract
The system SHALL preserve the existing backtest report, metrics, and trade CSV contract while internally routing execution through the paper broker.

#### Scenario: Existing trade fields remain available
- **WHEN** a paper-broker-routed backtest order fills
- **THEN** the trade recorder SHALL receive the same date, ticker, action, shares, price, and justification values that downstream reports already consume.

#### Scenario: Daily snapshots remain compatible
- **WHEN** a backtest day records a portfolio snapshot after paper-broker-routed execution
- **THEN** the snapshot SHALL retain the existing cashflow and positions dictionary shape used by metrics and report generation.
