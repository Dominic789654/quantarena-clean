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
AuditEvents = list[dict[str, Any]]

_BACKTEST_RISK_ENGINE = PreTradeRiskEngine(RiskLimits(require_market_open=False))
_PAPER_ORDER_SEQUENCE_KEY = "_paper_order_sequence"
_PAPER_FILL_SEQUENCE_KEY = "_paper_fill_sequence"


def convert_targets_to_trades(
    *,
    current_portfolio: Dict,
    target_positions: Dict[str, float],
    prices: Dict[str, float],
    date: str,
    record_trade: TradeRecorder,
    audit_events: AuditEvents | None = None,
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
                audit_events=audit_events,
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
                audit_events=audit_events,
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


def _cash_snapshot(current_portfolio: Dict[str, Any]) -> float:
    return float(current_portfolio.get("cashflow", 0.0) or 0.0)


def _positions_audit_snapshot(current_portfolio: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    positions: Dict[str, Dict[str, float]] = {}
    for symbol, position in sorted((current_portfolio.get("positions") or {}).items()):
        positions[str(symbol).upper()] = {
            "shares": int(position.get("shares", 0) or 0),
            "value": float(position.get("value", 0.0) or 0.0),
        }
    return positions


def _append_audit_event(
    audit_events: AuditEvents | None,
    *,
    date: str,
    ticker: str,
    side: str,
    requested_shares: int,
    approved_shares: int,
    requested_price: float,
    limit_price: float | None,
    order_id: str | None,
    fill_id: str | None,
    outcome: str,
    rejection_source: str | None,
    rejection_reason: str | None,
    risk_reasons: tuple[RiskReason, ...] | list[str],
    source_justification: str,
    cash_before: float,
    cash_after: float,
    positions_before: Dict[str, Dict[str, float]],
    positions_after: Dict[str, Dict[str, float]],
    risk_adjusted_shares: int | None = None,
) -> None:
    if audit_events is None:
        return

    normalized_risk_reasons = [
        reason.value if isinstance(reason, RiskReason) else str(reason)
        for reason in risk_reasons
    ]
    event: dict[str, Any] = {
        "date": date,
        "symbol": ticker.upper(),
        "side": side.upper(),
        "requested_shares": int(requested_shares),
        "approved_shares": int(approved_shares),
        "requested_price": float(requested_price),
        "limit_price": float(limit_price) if limit_price is not None else None,
        "order_id": order_id,
        "fill_id": fill_id,
        "outcome": outcome,
        "rejection_source": rejection_source,
        "rejection_reason": rejection_reason,
        "risk_reasons": normalized_risk_reasons,
        "source_justification": source_justification or "",
        "cash_before": float(cash_before),
        "cash_after": float(cash_after),
        "positions_before": positions_before,
        "positions_after": positions_after,
    }
    if risk_adjusted_shares is not None:
        event["risk_adjusted_shares"] = int(risk_adjusted_shares)
    audit_events.append(event)


def _append_risk_rejection_audit_event(
    audit_events: AuditEvents | None,
    *,
    current_portfolio: Dict[str, Any],
    date: str,
    ticker: str,
    side: str,
    requested_shares: int,
    requested_price: float,
    source_justification: str,
    validation,
) -> None:
    cash = _cash_snapshot(current_portfolio)
    positions = _positions_audit_snapshot(current_portfolio)
    _append_audit_event(
        audit_events,
        date=date,
        ticker=ticker,
        side=side,
        requested_shares=getattr(validation, "requested_shares", requested_shares),
        approved_shares=0,
        requested_price=requested_price,
        limit_price=requested_price,
        order_id=None,
        fill_id=None,
        outcome="rejected",
        rejection_source="risk_gate",
        rejection_reason=None,
        risk_reasons=validation.reasons,
        source_justification=source_justification,
        cash_before=cash,
        cash_after=cash,
        positions_before=positions,
        positions_after=positions,
        risk_adjusted_shares=getattr(validation, "adjusted_shares", 0),
    )


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
        next_order_sequence=_next_broker_sequence(current_portfolio, _PAPER_ORDER_SEQUENCE_KEY),
        next_fill_sequence=_next_broker_sequence(current_portfolio, _PAPER_FILL_SEQUENCE_KEY),
    )


def _next_broker_sequence(current_portfolio: Dict[str, Any], key: str) -> int:
    try:
        return max(1, int(current_portfolio.get(key, 1)))
    except (TypeError, ValueError):
        return 1


def _sync_broker_sequences_to_portfolio(
    *,
    current_portfolio: Dict[str, Any],
    broker: PaperBroker,
) -> None:
    current_portfolio[_PAPER_ORDER_SEQUENCE_KEY] = broker.next_order_sequence
    current_portfolio[_PAPER_FILL_SEQUENCE_KEY] = broker.next_fill_sequence


def _sync_portfolio_from_broker(
    *,
    current_portfolio: Dict[str, Any],
    broker: PaperBroker,
    prices: Dict[str, float],
) -> None:
    _sync_broker_sequences_to_portfolio(current_portfolio=current_portfolio, broker=broker)
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
    date: str,
    ticker: str,
    price: float,
    order,
    warn: WarningSink,
    audit_events: AuditEvents | None = None,
) -> bool:
    cash_before = _cash_snapshot(current_portfolio)
    positions_before = _positions_audit_snapshot(current_portfolio)
    broker = _paper_broker_from_portfolio(
        current_portfolio=current_portfolio,
        prices={ticker: price},
    )
    paper_order = broker.submit_order(order)
    if paper_order.status == BrokerOrderStatus.REJECTED:
        _sync_broker_sequences_to_portfolio(current_portfolio=current_portfolio, broker=broker)
        warn(f"Paper broker rejected {ticker} {order.side.value.lower()}: {paper_order.rejection_reason}")
        _append_audit_event(
            audit_events,
            date=date,
            ticker=ticker,
            side=order.side.value,
            requested_shares=int(order.metadata.get("requested_shares", order.shares)),
            approved_shares=order.shares,
            requested_price=float(order.metadata.get("latest_price", price)),
            limit_price=order.limit_price,
            order_id=paper_order.order_id,
            fill_id=None,
            outcome="rejected",
            rejection_source="paper_broker",
            rejection_reason=paper_order.rejection_reason,
            risk_reasons=order.adjustments,
            source_justification=order.source_justification,
            cash_before=cash_before,
            cash_after=_cash_snapshot(current_portfolio),
            positions_before=positions_before,
            positions_after=_positions_audit_snapshot(current_portfolio),
        )
        return False
    fill_result = broker.fill_order(paper_order.order_id, quantity=order.shares, price=price)
    if not fill_result.ok:
        _sync_broker_sequences_to_portfolio(current_portfolio=current_portfolio, broker=broker)
        warn(f"Paper broker rejected {ticker} {order.side.value.lower()} fill: {fill_result.error}")
        _append_audit_event(
            audit_events,
            date=date,
            ticker=ticker,
            side=order.side.value,
            requested_shares=int(order.metadata.get("requested_shares", order.shares)),
            approved_shares=order.shares,
            requested_price=float(order.metadata.get("latest_price", price)),
            limit_price=order.limit_price,
            order_id=paper_order.order_id,
            fill_id=None,
            outcome="rejected",
            rejection_source="paper_broker",
            rejection_reason=fill_result.error,
            risk_reasons=order.adjustments,
            source_justification=order.source_justification,
            cash_before=cash_before,
            cash_after=_cash_snapshot(current_portfolio),
            positions_before=positions_before,
            positions_after=_positions_audit_snapshot(current_portfolio),
        )
        return False
    _sync_portfolio_from_broker(
        current_portfolio=current_portfolio,
        broker=broker,
        prices={ticker: price},
    )
    _append_audit_event(
        audit_events,
        date=date,
        ticker=ticker,
        side=order.side.value,
        requested_shares=int(order.metadata.get("requested_shares", order.shares)),
        approved_shares=order.shares,
        requested_price=float(order.metadata.get("latest_price", price)),
        limit_price=order.limit_price,
        order_id=paper_order.order_id,
        fill_id=fill_result.fill.fill_id if fill_result.fill else None,
        outcome="filled",
        rejection_source=None,
        rejection_reason=None,
        risk_reasons=order.adjustments,
        source_justification=order.source_justification,
        cash_before=cash_before,
        cash_after=_cash_snapshot(current_portfolio),
        positions_before=positions_before,
        positions_after=_positions_audit_snapshot(current_portfolio),
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
    audit_events: AuditEvents | None = None,
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
        _append_risk_rejection_audit_event(
            audit_events,
            current_portfolio=current_portfolio,
            date=date,
            ticker=ticker,
            side="BUY",
            requested_shares=shares,
            requested_price=price,
            source_justification="",
            validation=validation,
        )
        return False

    if not _execute_paper_fill(
        current_portfolio=current_portfolio,
        date=date,
        ticker=ticker,
        price=validation.order.limit_price,
        order=validation.order,
        warn=warn,
        audit_events=audit_events,
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
    audit_events: AuditEvents | None = None,
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
        _append_risk_rejection_audit_event(
            audit_events,
            current_portfolio=current_portfolio,
            date=date,
            ticker=ticker,
            side="SELL",
            requested_shares=shares,
            requested_price=price,
            source_justification="",
            validation=validation,
        )
        return False
    if validation.adjusted_shares != shares:
        warn(_direct_warning(ticker, "sell", validation.reasons))

    sell_shares = validation.order.shares
    if not _execute_paper_fill(
        current_portfolio=current_portfolio,
        date=date,
        ticker=ticker,
        price=validation.order.limit_price,
        order=validation.order,
        warn=warn,
        audit_events=audit_events,
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
    audit_events: AuditEvents | None = None,
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
        _append_risk_rejection_audit_event(
            audit_events,
            current_portfolio=current_portfolio,
            date=date,
            ticker=ticker,
            side="BUY",
            requested_shares=shares_diff,
            requested_price=current_price,
            source_justification=justification,
            validation=validation,
        )
        return _risk_hold(_target_reason("Insufficient cash for target allocation", validation.reasons), validation.reasons)

    buy_shares = validation.order.shares
    if not _execute_paper_fill(
        current_portfolio=current_portfolio,
        date=date,
        ticker=ticker,
        price=validation.order.limit_price,
        order=validation.order,
        warn=lambda _message: None,
        audit_events=audit_events,
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
    audit_events: AuditEvents | None = None,
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
        _append_risk_rejection_audit_event(
            audit_events,
            current_portfolio=current_portfolio,
            date=date,
            ticker=ticker,
            side="SELL",
            requested_shares=sell_shares,
            requested_price=current_price,
            source_justification=justification,
            validation=validation,
        )
        return _risk_hold(_target_reason("No shares to sell", validation.reasons), validation.reasons)

    actual_sell = validation.order.shares
    if not _execute_paper_fill(
        current_portfolio=current_portfolio,
        date=date,
        ticker=ticker,
        price=validation.order.limit_price,
        order=validation.order,
        warn=lambda _message: None,
        audit_events=audit_events,
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
