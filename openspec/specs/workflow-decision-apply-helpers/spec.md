# workflow-decision-apply-helpers Specification

## Purpose
TBD - created by archiving change extract-workflow-decision-apply-helpers. Update Purpose after archive.
## Requirements
### Requirement: Decision normalization clamps shares to what is executable
`backtest.workflow.decision_apply._normalize_decision_for_portfolio(portfolio, ticker, decision)` SHALL return a `Decision` whose `shares` is clamped to `min(requested_shares, affordable_shares)` for `BUY` (based on `portfolio.cashflow // price`) or `min(requested_shares, current_shares)` for `SELL` (based on the ticker's current position), and SHALL downgrade the action to `HOLD` with zero shares when the clamped amount is non-positive or the requested action is not `BUY`/`SELL`.

#### Scenario: BUY request exceeding cash is clamped
- **WHEN** a `BUY` decision requests more shares than `portfolio.cashflow // price` affords
- **THEN** the returned decision's `shares` equals the affordable amount and its `action` remains `BUY`

#### Scenario: SELL request exceeding current position is clamped
- **WHEN** a `SELL` decision requests more shares than the ticker's current position holds
- **THEN** the returned decision's `shares` equals the current position size and its `action` remains `SELL`

#### Scenario: Zero executable shares downgrades to HOLD
- **WHEN** a `BUY` decision's affordable shares clamp to zero (insufficient cash)
- **THEN** the returned decision's `action` is `HOLD` and `shares` is `0`

### Requirement: Portfolio ticker update applies a normalized decision
`backtest.workflow.decision_apply._update_portfolio_ticker(portfolio, ticker, decision)` SHALL, for `BUY`, increase the ticker's shares and decrease `portfolio.cashflow` by `price * shares`, and for `SELL`, decrease shares and increase cashflow correspondingly, then recompute the ticker's `value` as `round(price * shares, 2)` and round `portfolio.cashflow` to 2 decimal places, mutating and returning the same `portfolio` object.

#### Scenario: BUY increases shares and decreases cashflow
- **WHEN** `_update_portfolio_ticker(portfolio, "AAA", buy_decision)` is called with a `BUY` decision for 10 shares at price 5.0
- **THEN** the ticker's shares increase by 10 and `portfolio.cashflow` decreases by 50.0 (rounded to 2 decimals)

### Requirement: workflow_adapter static-method delegators preserve call surfaces
`BacktestWorkflowAdapter` SHALL expose `_normalize_decision_for_portfolio` and `_update_portfolio_ticker` as `staticmethod` class attributes bound to `backtest.workflow.decision_apply`'s module functions, so both `BacktestWorkflowAdapter.<name>(...)` and `adapter.<name>(...)` call sites keep resolving and returning identical results.

#### Scenario: Instance-level call resolves to the module function
- **WHEN** `adapter._normalize_decision_for_portfolio(portfolio, ticker, decision)` is called on any `BacktestWorkflowAdapter` instance
- **THEN** it returns the same value as `backtest.workflow.decision_apply._normalize_decision_for_portfolio(portfolio, ticker, decision)`

