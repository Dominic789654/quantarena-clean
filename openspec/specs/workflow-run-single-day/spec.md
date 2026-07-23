# workflow-run-single-day Specification

## Purpose
TBD - created by archiving change add-run-single-day-characterization-test. Update Purpose after archive.
## Requirements
### Requirement: Happy path produces a BacktestDecision per priced ticker and updates the portfolio sequentially
`BacktestWorkflowAdapter.run_single_day(trading_date, prices)` SHALL, for each ticker present in both `self.tickers` and `prices`, build a `graph.workflow.AgentWorkflow`, invoke it, and — when it returns a decision — record a `BacktestDecision` with that decision's `action`, `shares`, `price`, and `justification`, then apply the decision to the working `Portfolio` via `workflow.update_portfolio_ticker` before processing the next ticker, so that one ticker's decision affects the cashflow available to the next.

#### Scenario: Two tickers processed in order, one BUY affects the next ticker's available cash
- **WHEN** `run_single_day` is called with tickers `AAA` (fake workflow returns BUY 10 @ 100.0) and `BBB` (fake workflow returns HOLD)
- **THEN** the returned decisions dict has `AAA.action == "BUY"`, `AAA.shares == 10`, `BBB.action == "HOLD"`, and the adapter's portfolio afterward has `cashflow == initial_cash - 1000.0` and `positions["AAA"]["shares"] == 10`

### Requirement: Import failure of the DeepFund workflow modules falls back to HOLD for every priced ticker
`BacktestWorkflowAdapter.run_single_day(trading_date, prices)` SHALL, if importing `graph.workflow`, `graph.schema`, `util.db_helper`, or `database.sqlite_helper` raises `ImportError`, return a `BacktestDecision` with `action="HOLD"`, `shares=0`, `price` equal to the ticker's priced value, and `justification` starting with `"Import error: "` for every ticker present in `prices`, and SHALL leave the portfolio state unmodified.

#### Scenario: graph.workflow unavailable holds every ticker without touching the portfolio
- **WHEN** `from graph.workflow import AgentWorkflow` raises `ImportError` during `run_single_day`
- **THEN** every ticker in `prices` gets a HOLD decision with an `"Import error: "`-prefixed justification, and the adapter's `cashflow` and position shares are unchanged from before the call

### Requirement: A single ticker's processing exception falls back to HOLD for that ticker only
`BacktestWorkflowAdapter.run_single_day(trading_date, prices)` SHALL, if building, invoking, or applying the decision for one ticker's workflow raises any `Exception` (not `ImportError`), record a `BacktestDecision` with `action="HOLD"`, `shares=0`, `price` equal to that ticker's priced value, and `justification` starting with `"Error: "` for that ticker only, and SHALL continue processing the remaining tickers normally, including applying their decisions to the same working portfolio.

#### Scenario: One ticker fails, the others still get real decisions and portfolio updates
- **WHEN** ticker `BBB`'s fake workflow raises inside `load_analysts` while tickers `AAA` and `CCC` return real BUY decisions
- **THEN** `BBB`'s decision is `action="HOLD"` with an `"Error: "`-prefixed justification, while `AAA` and `CCC` each get their BUY decision and the adapter's final portfolio reflects both `AAA` and `CCC`'s cash/share changes with `BBB`'s position left untouched

