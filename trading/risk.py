"""Deterministic pre-trade risk validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor, isfinite
from typing import Any, Mapping

from .order import OrderIntent, OrderSide, PreTradeValidationResult, RiskReason


@dataclass(frozen=True)
class PositionSnapshot:
    """Current broker or portfolio position for one symbol."""

    shares: int = 0
    market_value: float = 0.0


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Account state used by deterministic pre-trade checks."""

    cash: float
    positions: Mapping[str, PositionSnapshot] = field(default_factory=dict)
    total_value: float | None = None

    def position_for(self, symbol: str) -> PositionSnapshot:
        return self.positions.get(symbol.upper(), PositionSnapshot())

    def resolved_total_value(self, symbol: str, latest_price: float) -> float:
        if self.total_value is not None and self.total_value > 0:
            return float(self.total_value)
        positions_value = 0.0
        for ticker, position in self.positions.items():
            if position.market_value:
                positions_value += float(position.market_value)
            elif ticker.upper() == symbol.upper():
                positions_value += int(position.shares) * latest_price
        return float(self.cash) + positions_value


@dataclass(frozen=True)
class MarketSnapshot:
    """Market state required by the pre-trade gate."""

    latest_price: float | None = None
    is_open: bool | None = None


@dataclass(frozen=True)
class RiskLimits:
    """Hard pre-trade limits. Defaults are conservative for live use."""

    require_market_open: bool = True
    allow_short: bool = False
    max_order_notional: float | None = None
    max_position_weight: float | None = None
    price_collar_bps: float | None = None


class PreTradeRiskEngine:
    """Convert advisory model decisions into broker-neutral order intents."""

    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    def validate_decision(
        self,
        *,
        symbol: str,
        decision: Any,
        portfolio: PortfolioSnapshot,
        market: MarketSnapshot,
    ) -> PreTradeValidationResult:
        normalized_symbol = symbol.strip().upper()
        action = _normalize_action(getattr(decision, "action", None))
        requested_shares = _safe_int(getattr(decision, "shares", 0))
        decision_price = _safe_float(getattr(decision, "price", 0.0))
        source_justification = str(getattr(decision, "justification", "") or "")

        if not normalized_symbol:
            return _rejected(RiskReason.INVALID_DECISION, requested_shares, decision_price)
        if action is None:
            return _rejected(RiskReason.INVALID_ACTION, requested_shares, decision_price)
        if action == "HOLD":
            return PreTradeValidationResult(
                approved=True,
                reasons=(RiskReason.HOLD_DECISION,),
                adjusted_shares=0,
                requested_shares=requested_shares,
                requested_notional=0.0,
            )

        if requested_shares <= 0:
            return _rejected(RiskReason.INVALID_SHARES, requested_shares, decision_price)
        if decision_price <= 0 or not isfinite(decision_price):
            return _rejected(RiskReason.INVALID_PRICE, requested_shares, decision_price)
        if portfolio.cash < 0 or not isfinite(float(portfolio.cash)):
            return _rejected(RiskReason.INVALID_PORTFOLIO, requested_shares, decision_price)

        latest_price = market.latest_price if market.latest_price is not None else decision_price
        latest_price = _safe_float(latest_price)
        if latest_price <= 0 or not isfinite(latest_price):
            return _rejected(RiskReason.MISSING_QUOTE, requested_shares, decision_price)

        if self.limits.require_market_open and market.is_open is not True:
            return _rejected(RiskReason.MARKET_CLOSED, requested_shares, decision_price)

        if self.limits.price_collar_bps is not None and self.limits.price_collar_bps >= 0:
            collar = latest_price * (self.limits.price_collar_bps / 10_000)
            if abs(decision_price - latest_price) > collar:
                return _rejected(RiskReason.PRICE_COLLAR, requested_shares, decision_price)

        shares = requested_shares
        adjustments: list[RiskReason] = []

        if action == "BUY":
            shares = self._limit_buy_shares(
                normalized_symbol,
                shares,
                decision_price,
                portfolio,
                latest_price,
                adjustments,
            )
        else:
            shares = self._limit_sell_shares(normalized_symbol, shares, portfolio, adjustments)

        if shares <= 0:
            reason = adjustments[-1] if adjustments else RiskReason.MIN_SHARES
            return PreTradeValidationResult(
                approved=False,
                reasons=(reason,),
                adjusted_shares=0,
                requested_shares=requested_shares,
                requested_notional=requested_shares * decision_price,
            )

        side = OrderSide.BUY if action == "BUY" else OrderSide.SELL
        order = OrderIntent(
            symbol=normalized_symbol,
            side=side,
            shares=shares,
            limit_price=decision_price,
            source_action=action,
            source_justification=source_justification,
            adjustments=tuple(adjustments),
            metadata={
                "requested_shares": requested_shares,
                "requested_notional": requested_shares * decision_price,
                "latest_price": latest_price,
            },
        )
        return PreTradeValidationResult(
            approved=True,
            order=order,
            reasons=tuple(adjustments),
            adjusted_shares=shares,
            requested_shares=requested_shares,
            requested_notional=requested_shares * decision_price,
        )

    def _limit_buy_shares(
        self,
        symbol: str,
        shares: int,
        price: float,
        portfolio: PortfolioSnapshot,
        latest_price: float,
        adjustments: list[RiskReason],
    ) -> int:
        limited = shares
        affordable = floor(float(portfolio.cash) / price)
        if limited > affordable:
            limited = affordable
            adjustments.append(RiskReason.CASH_LIMIT)

        if self.limits.max_order_notional is not None:
            max_by_notional = floor(max(0.0, self.limits.max_order_notional) / price)
            if limited > max_by_notional:
                limited = max_by_notional
                adjustments.append(RiskReason.MAX_ORDER_NOTIONAL)

        if self.limits.max_position_weight is not None:
            total_value = portfolio.resolved_total_value(symbol, latest_price)
            if total_value <= 0:
                return 0
            position = portfolio.position_for(symbol)
            current_value = position.market_value or position.shares * latest_price
            max_symbol_value = max(0.0, self.limits.max_position_weight) * total_value
            remaining_value = max_symbol_value - current_value
            max_by_weight = floor(max(0.0, remaining_value) / price)
            if limited > max_by_weight:
                limited = max_by_weight
                adjustments.append(RiskReason.MAX_POSITION_WEIGHT)

        return max(0, limited)

    def _limit_sell_shares(
        self,
        symbol: str,
        shares: int,
        portfolio: PortfolioSnapshot,
        adjustments: list[RiskReason],
    ) -> int:
        position_shares = int(portfolio.position_for(symbol).shares)
        if not self.limits.allow_short and position_shares <= 0:
            adjustments.append(RiskReason.SHORT_NOT_ALLOWED)
            return 0

        limited = shares
        if not self.limits.allow_short and limited > position_shares:
            limited = position_shares
            adjustments.append(RiskReason.POSITION_LIMIT)
        return max(0, limited)


def _normalize_action(action: Any) -> str | None:
    value = getattr(action, "value", action)
    if value is None:
        return None
    normalized = str(value).strip().upper()
    if normalized in {"BUY", "SELL", "HOLD"}:
        return normalized
    return None


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _rejected(reason: RiskReason, requested_shares: int, price: float) -> PreTradeValidationResult:
    return PreTradeValidationResult(
        approved=False,
        reasons=(reason,),
        adjusted_shares=0,
        requested_shares=requested_shares,
        requested_notional=max(0, requested_shares) * max(0.0, price),
    )
