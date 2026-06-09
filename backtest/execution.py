"""Shared execution helpers for target-weight portfolio decisions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Dict

from trading import (
    MarketSnapshot,
    BrokerOrderStatus,
    PaperBroker,
    PortfolioSnapshot,
    PositionSnapshot,
    PreTradeRiskEngine,
    RiskLimits,
    RiskReason,
)


TradeRecorder = Callable[[str, str, str, int, float, str], None]
OrderTradeRecorder = Callable[[str, str, str, int, float], None]
SnapshotRecorder = Callable[[str, float, Dict[str, Any], Dict[str, float]], None]
WarningSink = Callable[[str], None]

_BACKTEST_RISK_ENGINE = PreTradeRiskEngine(RiskLimits(require_market_open=False))


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


def _portfolio_snapshot(*, current_portfolio: Dict[str, Any], ticker: str, price: float) -> PortfolioSnapshot:
    positions = {}
    for symbol, position in current_portfolio.get("positions", {}).items():
        shares = int(position.get("shares", 0) or 0)
        value = float(position.get("value", 0.0) or 0.0)
        if symbol == ticker and price > 0:
            value = shares * price
        positions[symbol.upper()] = PositionSnapshot(shares=shares, market_value=value)
    return PortfolioSnapshot(
        cash=float(current_portfolio.get("cashflow", 0.0) or 0.0),
        positions=positions,
        total_value=None,
    )


def _decision(action: str, shares: int, price: float, justification: str = "") -> SimpleNamespace:
    return SimpleNamespace(action=action, shares=shares, price=price, justification=justification)


def _risk_reason_values(reasons: tuple[RiskReason, ...]) -> list[str]:
    return [reason.value for reason in reasons]


def _risk_hold(reason: str, validation_reasons: tuple[RiskReason, ...]) -> Dict:
    return {
        "action": "HOLD",
        "shares": 0,
        "justification": reason,
        "_applied": True,
        "_risk_reasons": _risk_reason_values(validation_reasons),
    }


def _validate_backtest_order(
    *,
    current_portfolio: Dict[str, Any],
    ticker: str,
    action: str,
    shares: int,
    price: float,
    justification: str = "",
):
    return _BACKTEST_RISK_ENGINE.validate_decision(
        symbol=ticker,
        decision=_decision(action, shares, price, justification),
        portfolio=_portfolio_snapshot(current_portfolio=current_portfolio, ticker=ticker, price=price),
        market=MarketSnapshot(latest_price=price, is_open=True),
    )


def _direct_warning(ticker: str, action: str, reasons: tuple[RiskReason, ...]) -> str:
    if action == "buy" and RiskReason.CASH_LIMIT in reasons:
        return f"Insufficient cash for {ticker} buy"
    if action == "sell" and (
        RiskReason.POSITION_LIMIT in reasons or RiskReason.SHORT_NOT_ALLOWED in reasons
    ):
        return f"Insufficient shares for {ticker} sell"
    joined = ",".join(_risk_reason_values(reasons)) or "unknown"
    return f"Risk gate rejected {ticker} {action}: {joined}"


def _target_reason(default: str, reasons: tuple[RiskReason, ...]) -> str:
    if RiskReason.CASH_LIMIT in reasons:
        return "Insufficient cash for target allocation"
    if RiskReason.POSITION_LIMIT in reasons or RiskReason.SHORT_NOT_ALLOWED in reasons:
        return "No shares to sell"
    if RiskReason.INVALID_PRICE in reasons:
        return "Invalid price for target allocation"
    return default


def _paper_broker_from_portfolio(
    *,
    current_portfolio: Dict[str, Any],
    prices: Dict[str, float],
) -> PaperBroker:
    positions = {
        symbol: int(position.get("shares", 0) or 0)
        for symbol, position in current_portfolio.get("positions", {}).items()
    }
    quotes = {
        symbol: price
        for symbol, price in prices.items()
        if price is not None and price > 0
    }
    return PaperBroker(
        initial_cash=float(current_portfolio.get("cashflow", 0.0) or 0.0),
        positions=positions,
        quotes=quotes,
    )


def _sync_portfolio_from_broker(
    *,
    current_portfolio: Dict[str, Any],
    broker: PaperBroker,
    prices: Dict[str, float],
) -> None:
    current_portfolio["cashflow"] = broker.get_account().cash
    existing_positions = dict(current_portfolio.get("positions", {}))
    symbols = set(existing_positions) | set(broker.positions)
    synced_positions: Dict[str, Dict[str, float]] = {}
    for symbol in sorted(symbols):
        shares = int(broker.positions.get(symbol, 0))
        existing = existing_positions.get(symbol, {})
        price = prices.get(symbol)
        value = round(shares * float(price), 2) if price is not None else float(existing.get("value", 0.0) or 0.0)
        synced_positions[symbol] = {
            "shares": shares,
            "value": value,
        }
    current_portfolio["positions"] = synced_positions


def _execute_paper_fill(
    *,
    current_portfolio: Dict[str, Any],
    ticker: str,
    price: float,
    order,
    warn: WarningSink,
) -> bool:
    broker = _paper_broker_from_portfolio(
        current_portfolio=current_portfolio,
        prices={ticker: price},
    )
    paper_order = broker.submit_order(order)
    if paper_order.status == BrokerOrderStatus.REJECTED:
        warn(f"Paper broker rejected {ticker} {order.side.value.lower()}: {paper_order.rejection_reason}")
        return False
    fill_result = broker.fill_order(paper_order.order_id, quantity=order.shares, price=price)
    if not fill_result.ok:
        warn(f"Paper broker rejected {ticker} {order.side.value.lower()} fill: {fill_result.error}")
        return False
    _sync_portfolio_from_broker(
        current_portfolio=current_portfolio,
        broker=broker,
        prices={ticker: price},
    )
    return True


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
    """Apply a plain BUY order to portfolio state after risk validation."""
    validation = _validate_backtest_order(
        current_portfolio=current_portfolio,
        ticker=ticker,
        action="BUY",
        shares=shares,
        price=price,
    )
    if validation.rejected or validation.order is None or validation.adjusted_shares != shares:
        warn(_direct_warning(ticker, "buy", validation.reasons))
        return False

    if not _execute_paper_fill(
        current_portfolio=current_portfolio,
        ticker=ticker,
        price=validation.order.limit_price,
        order=validation.order,
        warn=warn,
    ):
        return False
    record_trade(date, ticker, "BUY", validation.order.shares, validation.order.limit_price)
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
    """Apply a plain SELL order to portfolio state after risk validation."""
    validation = _validate_backtest_order(
        current_portfolio=current_portfolio,
        ticker=ticker,
        action="SELL",
        shares=shares,
        price=price,
    )
    if validation.rejected or validation.order is None:
        warn(_direct_warning(ticker, "sell", validation.reasons))
        return False
    if validation.adjusted_shares != shares:
        warn(_direct_warning(ticker, "sell", validation.reasons))

    sell_shares = validation.order.shares
    if not _execute_paper_fill(
        current_portfolio=current_portfolio,
        ticker=ticker,
        price=validation.order.limit_price,
        order=validation.order,
        warn=warn,
    ):
        return False
    record_trade(date, ticker, "SELL", sell_shares, validation.order.limit_price)
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
    justification = f"Target allocation: {target_ratio:.1%} (current: {current_shares} shares)"
    validation = _validate_backtest_order(
        current_portfolio=current_portfolio,
        ticker=ticker,
        action="BUY",
        shares=shares_diff,
        price=current_price,
        justification=justification,
    )
    if validation.rejected or validation.order is None:
        return _risk_hold(_target_reason("Insufficient cash for target allocation", validation.reasons), validation.reasons)

    buy_shares = validation.order.shares
    if not _execute_paper_fill(
        current_portfolio=current_portfolio,
        ticker=ticker,
        price=validation.order.limit_price,
        order=validation.order,
        warn=lambda _message: None,
    ):
        return _risk_hold("Paper broker rejected target allocation", validation.reasons)
    record_trade(date, ticker, "BUY", buy_shares, validation.order.limit_price, justification)
    return {
        "action": "BUY",
        "shares": buy_shares,
        "justification": justification,
        "_applied": True,
        "_risk_reasons": _risk_reason_values(validation.reasons),
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
    justification = f"Target allocation: {target_ratio:.1%} (current: {current_shares} shares)"
    validation = _validate_backtest_order(
        current_portfolio=current_portfolio,
        ticker=ticker,
        action="SELL",
        shares=sell_shares,
        price=current_price,
        justification=justification,
    )
    if validation.rejected or validation.order is None:
        return _risk_hold(_target_reason("No shares to sell", validation.reasons), validation.reasons)

    actual_sell = validation.order.shares
    if not _execute_paper_fill(
        current_portfolio=current_portfolio,
        ticker=ticker,
        price=validation.order.limit_price,
        order=validation.order,
        warn=lambda _message: None,
    ):
        return _risk_hold("Paper broker rejected target allocation", validation.reasons)
    record_trade(date, ticker, "SELL", actual_sell, validation.order.limit_price, justification)
    return {
        "action": "SELL",
        "shares": actual_sell,
        "justification": justification,
        "_applied": True,
        "_risk_reasons": _risk_reason_values(validation.reasons),
    }
