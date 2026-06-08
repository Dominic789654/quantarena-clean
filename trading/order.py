"""Broker-neutral order intent and pre-trade validation models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class OrderSide(str, Enum):
    """Executable order side after advisory decisions pass risk checks."""

    BUY = "BUY"
    SELL = "SELL"


class RiskReason(str, Enum):
    """Machine-readable pre-trade rejection or adjustment reasons."""

    HOLD_DECISION = "hold_decision"
    INVALID_ACTION = "invalid_action"
    INVALID_DECISION = "invalid_decision"
    INVALID_PRICE = "invalid_price"
    INVALID_SHARES = "invalid_shares"
    INVALID_PORTFOLIO = "invalid_portfolio"
    MARKET_CLOSED = "market_closed"
    MISSING_QUOTE = "missing_quote"
    PRICE_COLLAR = "price_collar"
    CASH_LIMIT = "cash_limit"
    POSITION_LIMIT = "position_limit"
    SHORT_NOT_ALLOWED = "short_not_allowed"
    MAX_ORDER_NOTIONAL = "max_order_notional"
    MAX_POSITION_WEIGHT = "max_position_weight"
    MIN_SHARES = "min_shares"


@dataclass(frozen=True)
class OrderIntent:
    """A broker-neutral order proposal approved by deterministic pre-trade checks."""

    symbol: str
    side: OrderSide
    shares: int
    limit_price: float
    source_action: str
    source_justification: str = ""
    adjustments: tuple[RiskReason, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "shares", int(self.shares))
        object.__setattr__(self, "limit_price", float(self.limit_price))
        if not isinstance(self.side, OrderSide):
            object.__setattr__(self, "side", OrderSide(str(self.side).upper()))
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def notional(self) -> float:
        return self.shares * self.limit_price


@dataclass(frozen=True)
class PreTradeValidationResult:
    """Result returned by the pre-trade risk gate."""

    approved: bool
    order: OrderIntent | None = None
    reasons: tuple[RiskReason, ...] = ()
    adjusted_shares: int = 0
    requested_shares: int = 0
    requested_notional: float = 0.0

    @property
    def rejected(self) -> bool:
        return not self.approved

    @property
    def has_order(self) -> bool:
        return self.order is not None
