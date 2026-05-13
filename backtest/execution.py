"""Shared execution helpers for target-weight portfolio decisions."""

from __future__ import annotations

from typing import Any, Callable, Dict


TradeRecorder = Callable[[str, str, str, int, float, str], None]
OrderTradeRecorder = Callable[[str, str, str, int, float], None]
SnapshotRecorder = Callable[[str, float, Dict[str, Any], Dict[str, float]], None]
WarningSink = Callable[[str], None]


def convert_targets_to_trades(
    *,
    current_portfolio: Dict,
    target_positions: Dict[str, float],
    prices: Dict[str, float],
    date: str,
    record_trade: TradeRecorder,
) -> Dict[str, Dict]:
    """Convert target position weights into applied trade decisions.

    The helper mutates ``current_portfolio`` and records trades through
    ``record_trade``. This preserves the existing BacktestEngine contract where
    returned decisions are marked ``_applied=True`` and must not be executed a
    second time by the daily loop.
    """
    decisions: Dict[str, Dict] = {}
    total_value = _portfolio_value(current_portfolio=current_portfolio, prices=prices)

    for ticker, target_ratio in target_positions.items():
        if ticker not in prices:
            continue

        current_shares = current_portfolio["positions"].get(ticker, {}).get("shares", 0)
        current_price = prices[ticker]
        target_shares = int((total_value * target_ratio) / current_price) if current_price > 0 else 0
        shares_diff = target_shares - current_shares

        if shares_diff > 0:
            decisions[ticker] = _apply_target_buy(
                current_portfolio=current_portfolio,
                ticker=ticker,
                target_ratio=target_ratio,
                current_shares=current_shares,
                current_price=current_price,
                shares_diff=shares_diff,
                date=date,
                record_trade=record_trade,
            )
        elif shares_diff < 0:
            decisions[ticker] = _apply_target_sell(
                current_portfolio=current_portfolio,
                ticker=ticker,
                target_ratio=target_ratio,
                current_shares=current_shares,
                current_price=current_price,
                shares_diff=shares_diff,
                date=date,
                record_trade=record_trade,
            )
        else:
            decisions[ticker] = {
                "action": "HOLD",
                "shares": 0,
                "justification": f"Target allocation {target_ratio:.1%} achieved",
                "_applied": True,
            }

    return decisions


def _portfolio_value(*, current_portfolio: Dict, prices: Dict[str, float]) -> float:
    total_value = current_portfolio["cashflow"]
    for ticker, pos in current_portfolio["positions"].items():
        shares = pos.get("shares", 0)
        if ticker in prices and shares > 0:
            total_value += shares * prices[ticker]
    return total_value


def execute_buy_order(
    *,
    current_portfolio: Dict[str, Any],
    date: str,
    ticker: str,
    shares: int,
    price: float,
    record_trade: OrderTradeRecorder,
    warn: WarningSink,
) -> bool:
    """Apply a plain BUY order to portfolio state and record the trade."""
    cost = shares * price
    if cost > current_portfolio["cashflow"]:
        warn(f"Insufficient cash for {ticker} buy")
        return False

    current_portfolio["cashflow"] -= cost
    current_shares = current_portfolio["positions"][ticker]["shares"]
    new_shares = current_shares + shares
    current_portfolio["positions"][ticker] = {
        "shares": new_shares,
        "value": round(new_shares * price, 2),
    }
    record_trade(date, ticker, "BUY", shares, price)
    return True


def execute_sell_order(
    *,
    current_portfolio: Dict[str, Any],
    date: str,
    ticker: str,
    shares: int,
    price: float,
    record_trade: OrderTradeRecorder,
    warn: WarningSink,
) -> bool:
    """Apply a plain SELL order to portfolio state and record the trade."""
    current_pos = current_portfolio["positions"].get(ticker, {})
    current_shares = current_pos.get("shares", 0)
    if shares > current_shares:
        warn(f"Insufficient shares for {ticker} sell")
        shares = current_shares

    if shares <= 0:
        return False

    proceeds = shares * price
    current_portfolio["cashflow"] += proceeds
    new_shares = current_shares - shares
    current_portfolio["positions"][ticker] = {
        "shares": new_shares,
        "value": round(new_shares * price, 2),
    }
    record_trade(date, ticker, "SELL", shares, price)
    return True


def record_portfolio_snapshot(
    *,
    current_portfolio: Dict[str, Any],
    date: str,
    prices: Dict[str, float],
    record_snapshot: SnapshotRecorder,
) -> None:
    """Update marked position values and record a daily portfolio snapshot."""
    for ticker, pos in current_portfolio["positions"].items():
        if ticker in prices:
            pos["value"] = round(pos["shares"] * prices[ticker], 2)

    record_snapshot(
        date,
        current_portfolio["cashflow"],
        current_portfolio["positions"].copy(),
        prices,
    )


def _apply_target_buy(
    *,
    current_portfolio: Dict,
    ticker: str,
    target_ratio: float,
    current_shares: int,
    current_price: float,
    shares_diff: int,
    date: str,
    record_trade: TradeRecorder,
) -> Dict:
    max_affordable = int(current_portfolio["cashflow"] / current_price) if current_price > 0 else 0
    buy_shares = min(shares_diff, max_affordable)
    if buy_shares <= 0:
        return {
            "action": "HOLD",
            "shares": 0,
            "justification": "Insufficient cash for target allocation",
            "_applied": True,
        }

    justification = f"Target allocation: {target_ratio:.1%} (current: {current_shares} shares)"
    current_portfolio["cashflow"] -= buy_shares * current_price
    current_portfolio["positions"][ticker] = {
        "shares": current_shares + buy_shares,
        "value": (current_shares + buy_shares) * current_price,
    }
    record_trade(date, ticker, "BUY", buy_shares, current_price, justification)
    return {
        "action": "BUY",
        "shares": buy_shares,
        "justification": justification,
        "_applied": True,
    }


def _apply_target_sell(
    *,
    current_portfolio: Dict,
    ticker: str,
    target_ratio: float,
    current_shares: int,
    current_price: float,
    shares_diff: int,
    date: str,
    record_trade: TradeRecorder,
) -> Dict:
    sell_shares = abs(shares_diff)
    actual_sell = min(sell_shares, current_shares)
    if actual_sell <= 0:
        return {
            "action": "HOLD",
            "shares": 0,
            "justification": "No shares to sell",
            "_applied": True,
        }

    justification = f"Target allocation: {target_ratio:.1%} (current: {current_shares} shares)"
    current_portfolio["cashflow"] += actual_sell * current_price
    new_shares = current_shares - actual_sell
    current_portfolio["positions"][ticker] = {
        "shares": new_shares,
        "value": new_shares * current_price,
    }
    record_trade(date, ticker, "SELL", actual_sell, current_price, justification)
    return {
        "action": "SELL",
        "shares": actual_sell,
        "justification": justification,
        "_applied": True,
    }
