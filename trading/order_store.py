"""Order storage primitives for paper and future broker adapters."""

from __future__ import annotations

from collections import OrderedDict
from typing import Iterable

from .broker import BrokerOrder, BrokerOrderStatus


class InMemoryOrderStore:
    """Small deterministic in-memory order store."""

    def __init__(self) -> None:
        self._orders: OrderedDict[str, BrokerOrder] = OrderedDict()

    def create(self, order: BrokerOrder) -> BrokerOrder:
        """Create an order, rejecting duplicate order ids."""
        if order.order_id in self._orders:
            raise ValueError(f"order already exists: {order.order_id}")
        self._orders[order.order_id] = order
        return order

    def update(self, order: BrokerOrder) -> BrokerOrder:
        """Replace an existing order."""
        if order.order_id not in self._orders:
            raise KeyError(f"unknown order: {order.order_id}")
        self._orders[order.order_id] = order
        return order

    def get(self, order_id: str) -> BrokerOrder | None:
        """Return one order by id."""
        return self._orders.get(order_id)

    def require(self, order_id: str) -> BrokerOrder:
        """Return one order by id or raise KeyError."""
        order = self.get(order_id)
        if order is None:
            raise KeyError(f"unknown order: {order_id}")
        return order

    def list(
        self,
        *,
        status: BrokerOrderStatus | None = None,
        symbol: str | None = None,
    ) -> list[BrokerOrder]:
        """List stored orders in insertion order."""
        orders: Iterable[BrokerOrder] = self._orders.values()
        if status is not None:
            normalized_status = status if isinstance(status, BrokerOrderStatus) else BrokerOrderStatus(status)
            orders = [order for order in orders if order.status == normalized_status]
        if symbol is not None:
            normalized_symbol = symbol.strip().upper()
            orders = [order for order in orders if order.symbol == normalized_symbol]
        return list(orders)

    def open_orders(self) -> list[BrokerOrder]:
        """Return orders that can still be filled or cancelled."""
        return [order for order in self._orders.values() if not order.is_terminal]
