"""Pure helpers for applying a portfolio-manager decision to a working
Portfolio: clamping requested shares to what is executable, and
mutating the portfolio to reflect the (normalized) decision.

Moved verbatim (behavior-preserving) from `BacktestWorkflowAdapter`
static methods by the extract-workflow-decision-apply-helpers change
(docs/refactor_program_plan.md Phase 3). `backtest/workflow_adapter.py`
keeps same-named `staticmethod` class attributes pointing at these
module functions so every existing
`adapter._normalize_decision_for_portfolio(...)` /
`adapter._update_portfolio_ticker(...)` call keeps working.
"""

from typing import Any


def _normalize_decision_for_portfolio(portfolio: Any, ticker: str, decision: Any) -> Any:
    """Clamp a decision to the shares currently executable for the working portfolio."""
    from graph.constants import Action
    from graph.schema import Decision, Position

    action = str(getattr(decision, "action", "HOLD")).strip().upper()
    requested_shares = max(int(getattr(decision, "shares", 0) or 0), 0)
    price = float(getattr(decision, "price", 0.0) or 0.0)
    justification = str(getattr(decision, "justification", "") or "")

    if ticker not in portfolio.positions:
        portfolio.positions[ticker] = Position(shares=0, value=0)

    current_shares = int(getattr(portfolio.positions[ticker], "shares", 0) or 0)
    affordable_shares = int(portfolio.cashflow // price) if price > 0 else 0

    executable_shares = 0
    normalized_action = action
    if action == "BUY":
        executable_shares = min(requested_shares, affordable_shares)
        if executable_shares <= 0:
            normalized_action = "HOLD"
    elif action == "SELL":
        executable_shares = min(requested_shares, current_shares)
        if executable_shares <= 0:
            normalized_action = "HOLD"
    else:
        normalized_action = "HOLD"

    action_enum = Action.HOLD
    if normalized_action == "BUY":
        action_enum = Action.BUY
    elif normalized_action == "SELL":
        action_enum = Action.SELL

    return Decision(
        action=action_enum,
        shares=executable_shares,
        price=price,
        justification=justification,
    )


def _update_portfolio_ticker(portfolio: Any, ticker: str, decision: Any) -> Any:
    """Update one ticker in portfolio based on a portfolio manager decision."""
    from graph.schema import Position

    action = str(getattr(decision, "action", "HOLD")).strip().upper()
    shares = int(getattr(decision, "shares", 0) or 0)
    price = float(getattr(decision, "price", 0.0) or 0.0)

    if ticker not in portfolio.positions:
        portfolio.positions[ticker] = Position(shares=0, value=0)

    if action == "BUY":
        portfolio.positions[ticker].shares += shares
        portfolio.cashflow -= price * shares
    elif action == "SELL":
        portfolio.positions[ticker].shares -= shares
        portfolio.cashflow += price * shares

    portfolio.positions[ticker].value = round(price * portfolio.positions[ticker].shares, 2)
    portfolio.cashflow = round(portfolio.cashflow, 2)
    return portfolio
