"""Broker-neutral account, order, and fill models."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .order import OrderIntent, OrderSide


class BrokerOrderStatus(str, Enum):
    """Lifecycle status for broker or paper-broker orders."""

    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"


TERMINAL_ORDER_STATUSES = frozenset(
    {
        BrokerOrderStatus.REJECTED,
        BrokerOrderStatus.FILLED,
        BrokerOrderStatus.CANCELLED,
    }
)


@dataclass(frozen=True)
class AccountSnapshot:
    """Broker account state at one point in time."""

    cash: float
    total_value: float
    buying_power: float | None = None
    currency: str = "USD"

    def __post_init__(self) -> None:
        object.__setattr__(self, "cash", float(self.cash))
        object.__setattr__(self, "total_value", float(self.total_value))
        if self.buying_power is not None:
            object.__setattr__(self, "buying_power", float(self.buying_power))


@dataclass(frozen=True)
class BrokerPosition:
    """Broker position snapshot for one symbol."""

    symbol: str
    shares: int
    market_value: float = 0.0
    last_price: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "shares", int(self.shares))
        object.__setattr__(self, "market_value", float(self.market_value))
        if self.last_price is not None:
            object.__setattr__(self, "last_price", float(self.last_price))


@dataclass(frozen=True)
class Quote:
    """Latest quote used by a broker or paper broker."""

    symbol: str
    price: float
    bid: float | None = None
    ask: float | None = None
    timestamp: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "price", float(self.price))
        if self.bid is not None:
            object.__setattr__(self, "bid", float(self.bid))
        if self.ask is not None:
            object.__setattr__(self, "ask", float(self.ask))


@dataclass(frozen=True)
class Fill:
    """Executed quantity for a broker order."""

    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    timestamp: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        if not isinstance(self.side, OrderSide):
            object.__setattr__(self, "side", OrderSide(str(self.side).upper()))
        object.__setattr__(self, "quantity", int(self.quantity))
        object.__setattr__(self, "price", float(self.price))
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def notional(self) -> float:
        return self.quantity * self.price


@dataclass(frozen=True)
class BrokerOrder:
    """Order stored by a broker or paper broker."""

    order_id: str
    intent: OrderIntent
    status: BrokerOrderStatus
    filled_quantity: int = 0
    fills: tuple[Fill, ...] = ()
    rejection_reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, BrokerOrderStatus):
            object.__setattr__(self, "status", BrokerOrderStatus(str(self.status)))
        object.__setattr__(self, "filled_quantity", int(self.filled_quantity))
        if not isinstance(self.fills, tuple):
            object.__setattr__(self, "fills", tuple(self.fills))
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def remaining_quantity(self) -> int:
        return max(0, self.intent.shares - self.filled_quantity)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ORDER_STATUSES

    @property
    def side(self) -> OrderSide:
        return self.intent.side

    @property
    def symbol(self) -> str:
        return self.intent.symbol

    def with_status(
        self,
        status: BrokerOrderStatus,
        *,
        rejection_reason: str | None = None,
    ) -> "BrokerOrder":
        return replace(self, status=status, rejection_reason=rejection_reason)

    def with_fill(self, fill: Fill) -> "BrokerOrder":
        filled_quantity = self.filled_quantity + fill.quantity
        status = (
            BrokerOrderStatus.FILLED
            if filled_quantity >= self.intent.shares
            else BrokerOrderStatus.PARTIAL_FILLED
        )
        return replace(
            self,
            status=status,
            filled_quantity=filled_quantity,
            fills=(*self.fills, fill),
        )
