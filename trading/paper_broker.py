"""Deterministic paper broker implementation."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from math import isfinite
from typing import Mapping

from .broker import (
    AccountSnapshot,
    BrokerOrder,
    BrokerOrderStatus,
    BrokerPosition,
    Fill,
    Quote,
)
from .order import OrderIntent, OrderSide
from .order_store import InMemoryOrderStore


@dataclass(frozen=True)
class FillResult:
    """Result of applying a fill to a paper order."""

    ok: bool
    order: BrokerOrder
    fill: Fill | None = None
    error: str | None = None


@dataclass(frozen=True)
class CancelResult:
    """Result of attempting to cancel a paper order."""

    cancelled: bool
    order: BrokerOrder
    reason: str | None = None


class PaperBroker:
    """Local broker simulation with explicit order lifecycle and accounting."""

    def __init__(
        self,
        *,
        initial_cash: float,
        positions: Mapping[str, int] | None = None,
        quotes: Mapping[str, Quote | float] | None = None,
        order_store: InMemoryOrderStore | None = None,
        allow_short: bool = False,
        allow_negative_cash: bool = False,
        next_order_sequence: int = 1,
        next_fill_sequence: int = 1,
    ) -> None:
        self.cash = float(initial_cash)
        self.positions: dict[str, int] = {
            symbol.strip().upper(): int(shares)
            for symbol, shares in (positions or {}).items()
            if symbol.strip()
        }
        self.quotes: dict[str, Quote] = {}
        for symbol, quote in (quotes or {}).items():
            self.set_quote(symbol, quote)
        self.order_store = order_store or InMemoryOrderStore()
        self.allow_short = allow_short
        self.allow_negative_cash = allow_negative_cash
        self._next_order_sequence = max(1, int(next_order_sequence))
        self._next_fill_sequence = max(1, int(next_fill_sequence))
        self._order_counter = count(self._next_order_sequence)
        self._fill_counter = count(self._next_fill_sequence)

    def submit_order(self, intent: OrderIntent) -> BrokerOrder:
        """Submit a paper order and immediately accept or reject it."""
        order_id = self._next_order_id()
        if intent.shares <= 0:
            return self._create_rejected_order(order_id, intent, "invalid shares")
        if intent.limit_price <= 0 or not isfinite(intent.limit_price):
            return self._create_rejected_order(order_id, intent, "invalid limit price")

        order = BrokerOrder(
            order_id=order_id,
            intent=intent,
            status=BrokerOrderStatus.ACCEPTED,
        )
        return self.order_store.create(order)

    def fill_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
        timestamp: str | None = None,
    ) -> FillResult:
        """Apply a full or partial fill to an accepted paper order."""
        order = self.order_store.require(order_id)
        if order.is_terminal:
            return FillResult(ok=False, order=order, error=f"order is terminal: {order.status.value}")
        if order.status == BrokerOrderStatus.SUBMITTED:
            order = self.order_store.update(order.with_status(BrokerOrderStatus.ACCEPTED))

        fill_quantity = order.remaining_quantity if quantity is None else int(quantity)
        fill_price = order.intent.limit_price if price is None else float(price)
        if fill_quantity <= 0:
            return FillResult(ok=False, order=order, error="fill quantity must be positive")
        if fill_quantity > order.remaining_quantity:
            return FillResult(ok=False, order=order, error="fill quantity exceeds remaining quantity")
        if fill_price <= 0 or not isfinite(fill_price):
            return FillResult(ok=False, order=order, error="fill price must be positive")

        accounting_error = self._validate_fill_accounting(order, fill_quantity, fill_price)
        if accounting_error:
            return FillResult(ok=False, order=order, error=accounting_error)

        fill = Fill(
            fill_id=self._next_fill_id(),
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=fill_quantity,
            price=fill_price,
            timestamp=timestamp,
        )
        self._apply_fill(fill)
        self.set_quote(order.symbol, fill_price)
        updated_order = self.order_store.update(order.with_fill(fill))
        return FillResult(ok=True, order=updated_order, fill=fill)

    def cancel_order(self, order_id: str) -> CancelResult:
        """Cancel an open paper order."""
        order = self.order_store.require(order_id)
        if order.is_terminal:
            return CancelResult(
                cancelled=False,
                order=order,
                reason=f"order is terminal: {order.status.value}",
            )
        updated_order = self.order_store.update(order.with_status(BrokerOrderStatus.CANCELLED))
        return CancelResult(cancelled=True, order=updated_order)

    def get_account(self) -> AccountSnapshot:
        """Return current account snapshot."""
        total_value = self.cash + sum(self._position_market_value(symbol) for symbol in self.positions)
        return AccountSnapshot(cash=self.cash, total_value=total_value, buying_power=self.cash)

    def get_positions(self) -> list[BrokerPosition]:
        """Return current non-zero positions."""
        return [
            BrokerPosition(
                symbol=symbol,
                shares=shares,
                market_value=self._position_market_value(symbol),
                last_price=self.quotes.get(symbol).price if symbol in self.quotes else None,
            )
            for symbol, shares in sorted(self.positions.items())
            if shares != 0
        ]

    def get_orders(
        self,
        *,
        status: BrokerOrderStatus | None = None,
        symbol: str | None = None,
    ) -> list[BrokerOrder]:
        """Return stored paper orders."""
        return self.order_store.list(status=status, symbol=symbol)

    def get_order(self, order_id: str) -> BrokerOrder | None:
        """Return one stored paper order."""
        return self.order_store.get(order_id)

    def get_quotes(self, symbols: list[str] | tuple[str, ...]) -> dict[str, Quote]:
        """Return known quotes for the requested symbols."""
        return {
            symbol.strip().upper(): self.quotes[symbol.strip().upper()]
            for symbol in symbols
            if symbol.strip().upper() in self.quotes
        }

    def set_quote(self, symbol: str, quote: Quote | float) -> Quote:
        """Set or replace a quote."""
        normalized_symbol = symbol.strip().upper()
        normalized_quote = quote if isinstance(quote, Quote) else Quote(symbol=normalized_symbol, price=quote)
        self.quotes[normalized_symbol] = normalized_quote
        return normalized_quote

    def _create_rejected_order(
        self,
        order_id: str,
        intent: OrderIntent,
        reason: str,
    ) -> BrokerOrder:
        order = BrokerOrder(
            order_id=order_id,
            intent=intent,
            status=BrokerOrderStatus.REJECTED,
            rejection_reason=reason,
        )
        return self.order_store.create(order)

    def _validate_fill_accounting(
        self,
        order: BrokerOrder,
        quantity: int,
        price: float,
    ) -> str | None:
        notional = quantity * price
        if order.side == OrderSide.BUY:
            if not self.allow_negative_cash and notional > self.cash + 1e-9:
                return "insufficient cash"
            return None

        current_shares = self.positions.get(order.symbol, 0)
        if not self.allow_short and quantity > current_shares:
            return "insufficient position"
        return None

    def _apply_fill(self, fill: Fill) -> None:
        if fill.side == OrderSide.BUY:
            self.cash -= fill.notional
            self.positions[fill.symbol] = self.positions.get(fill.symbol, 0) + fill.quantity
        else:
            self.cash += fill.notional
            self.positions[fill.symbol] = self.positions.get(fill.symbol, 0) - fill.quantity

    def _position_market_value(self, symbol: str) -> float:
        shares = self.positions.get(symbol, 0)
        quote = self.quotes.get(symbol)
        price = quote.price if quote else 0.0
        return shares * price

    def _next_order_id(self) -> str:
        sequence = next(self._order_counter)
        self._next_order_sequence = sequence + 1
        return f"paper-{sequence:06d}"

    def _next_fill_id(self) -> str:
        sequence = next(self._fill_counter)
        self._next_fill_sequence = sequence + 1
        return f"fill-{sequence:06d}"

    @property
    def next_order_sequence(self) -> int:
        """Return the sequence value that will be used for the next order id."""
        return self._next_order_sequence

    @property
    def next_fill_sequence(self) -> int:
        """Return the sequence value that will be used for the next fill id."""
        return self._next_fill_sequence
