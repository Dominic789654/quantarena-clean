"""Persistent command interface for the local paper portfolio."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from shared.utils.path_manager import get_project_root

from .broker import (
    BrokerOrder,
    BrokerOrderStatus,
    Fill,
    Quote,
)
from .order import OrderIntent, OrderSide
from .order_store import InMemoryOrderStore
from .paper_broker import PaperBroker
from .reconciliation import reconcile_account


DEFAULT_PAPER_STATE_PATH = Path("data/paper_portfolio/state.json")
STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PaperCommandResult:
    """JSON-ready paper portfolio command result."""

    ok: bool
    command: str
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "command": self.command,
            "result": self.result or {},
            "error": self.error,
        }


class PaperPortfolioManager:
    """Load, operate, and persist a local paper broker state file."""

    def __init__(self, state_path: str | Path | None = None):
        self.state_path = _resolve_state_path(state_path)

    def init(self, *, initial_cash: float, overwrite: bool = False) -> PaperCommandResult:
        """Initialize the paper portfolio state file."""
        if self.state_path.exists() and not overwrite:
            return PaperCommandResult(
                ok=False,
                command="init",
                error=f"state already exists: {self.state_path}",
            )
        broker = PaperBroker(initial_cash=initial_cash)
        self._save_broker(broker)
        return PaperCommandResult(
            ok=True,
            command="init",
            result={"state_path": str(self.state_path), "account": _account_payload(broker)},
        )

    def account(self) -> PaperCommandResult:
        broker = self._load_broker()
        return PaperCommandResult(ok=True, command="account", result={"account": _account_payload(broker)})

    def positions(self) -> PaperCommandResult:
        broker = self._load_broker()
        return PaperCommandResult(
            ok=True,
            command="positions",
            result={"positions": _positions_payload(broker)},
        )

    def orders(self, *, status: str | None = None, symbol: str | None = None) -> PaperCommandResult:
        broker = self._load_broker()
        normalized_status = BrokerOrderStatus(status) if status else None
        return PaperCommandResult(
            ok=True,
            command="orders",
            result={
                "orders": [
                    _order_payload(order)
                    for order in broker.get_orders(status=normalized_status, symbol=symbol)
                ]
            },
        )

    def quotes(self, *, symbols: list[str] | None = None) -> PaperCommandResult:
        broker = self._load_broker()
        requested = symbols or sorted(broker.quotes)
        return PaperCommandResult(
            ok=True,
            command="quotes",
            result={
                "quotes": {
                    symbol: _quote_payload(quote)
                    for symbol, quote in broker.get_quotes(requested).items()
                }
            },
        )

    def set_quote(self, *, symbol: str, price: float) -> PaperCommandResult:
        broker = self._load_broker()
        quote = broker.set_quote(symbol, price)
        self._save_broker(broker)
        return PaperCommandResult(
            ok=True,
            command="quote.set",
            result={"quote": _quote_payload(quote), "account": _account_payload(broker)},
        )

    def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        shares: int,
        limit_price: float,
        justification: str = "",
    ) -> PaperCommandResult:
        broker = self._load_broker()
        try:
            normalized_side = OrderSide(side.strip().upper())
        except ValueError:
            return PaperCommandResult(ok=False, command="order.submit", error=f"invalid side: {side}")
        intent = OrderIntent(
            symbol=symbol,
            side=normalized_side,
            shares=shares,
            limit_price=limit_price,
            source_action=normalized_side.value,
            source_justification=justification or "manual paper command",
            metadata={"source": "paper_portfolio_command"},
        )
        order = broker.submit_order(intent)
        self._save_broker(broker)
        return PaperCommandResult(
            ok=order.status != BrokerOrderStatus.REJECTED,
            command="order.submit",
            result={"order": _order_payload(order)},
            error=order.rejection_reason,
        )

    def fill_order(
        self,
        *,
        order_id: str,
        quantity: int | None = None,
        price: float | None = None,
    ) -> PaperCommandResult:
        broker = self._load_broker()
        fill_result = broker.fill_order(order_id, quantity=quantity, price=price)
        if fill_result.ok:
            self._save_broker(broker)
        return PaperCommandResult(
            ok=fill_result.ok,
            command="order.fill",
            result={
                "order": _order_payload(fill_result.order),
                "fill": _fill_payload(fill_result.fill) if fill_result.fill else None,
                "account": _account_payload(broker),
                "positions": _positions_payload(broker),
            },
            error=fill_result.error,
        )

    def cancel_order(self, *, order_id: str) -> PaperCommandResult:
        broker = self._load_broker()
        cancel_result = broker.cancel_order(order_id)
        if cancel_result.cancelled:
            self._save_broker(broker)
        return PaperCommandResult(
            ok=cancel_result.cancelled,
            command="order.cancel",
            result={"order": _order_payload(cancel_result.order)},
            error=cancel_result.reason,
        )

    def reconcile(
        self,
        *,
        expected_cash: float,
        expected_positions: Mapping[str, int],
    ) -> PaperCommandResult:
        broker = self._load_broker()
        report = reconcile_account(
            expected_cash=expected_cash,
            expected_positions=expected_positions,
            account=broker.get_account(),
            positions=broker.get_positions(),
        )
        return PaperCommandResult(
            ok=report.ok,
            command="reconcile",
            result={
                "differences": [
                    {
                        "kind": diff.kind,
                        "symbol": diff.symbol,
                        "expected": diff.expected,
                        "actual": diff.actual,
                    }
                    for diff in report.differences
                ]
            },
            error=None if report.ok else "reconciliation differences found",
        )

    def _load_broker(self) -> PaperBroker:
        if not self.state_path.is_file():
            raise FileNotFoundError(f"paper portfolio state not found: {self.state_path}")
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        return broker_from_state(payload)

    def _save_broker(self, broker: PaperBroker) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = broker_to_state(broker)
        tmp_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.state_path)


def broker_to_state(broker: PaperBroker) -> dict[str, Any]:
    """Serialize a paper broker to a JSON-ready state payload."""
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "cash": broker.cash,
        "positions": dict(sorted(broker.positions.items())),
        "quotes": {
            symbol: _quote_payload(quote)
            for symbol, quote in sorted(broker.quotes.items())
        },
        "orders": [_order_payload(order) for order in broker.get_orders()],
    }


def broker_from_state(payload: Mapping[str, Any]) -> PaperBroker:
    """Rehydrate a paper broker from a state payload."""
    if int(payload.get("schema_version", 0)) != STATE_SCHEMA_VERSION:
        raise ValueError("unsupported paper portfolio state schema")
    quotes = {
        symbol: Quote(
            symbol=symbol,
            price=quote["price"],
            bid=quote.get("bid"),
            ask=quote.get("ask"),
            timestamp=quote.get("timestamp"),
        )
        for symbol, quote in (payload.get("quotes") or {}).items()
    }
    store = InMemoryOrderStore()
    broker = PaperBroker(
        initial_cash=float(payload.get("cash", 0.0)),
        positions={symbol: int(shares) for symbol, shares in (payload.get("positions") or {}).items()},
        quotes=quotes,
        order_store=store,
    )
    for order_payload in payload.get("orders") or []:
        store.create(_order_from_payload(order_payload))
    return broker


def _order_from_payload(payload: Mapping[str, Any]) -> BrokerOrder:
    intent_payload = payload["intent"]
    intent = OrderIntent(
        symbol=intent_payload["symbol"],
        side=OrderSide(intent_payload["side"]),
        shares=intent_payload["shares"],
        limit_price=intent_payload["limit_price"],
        source_action=intent_payload.get("source_action", intent_payload["side"]),
        source_justification=intent_payload.get("source_justification", ""),
        metadata=intent_payload.get("metadata") or {},
    )
    fills = tuple(_fill_from_payload(fill_payload) for fill_payload in payload.get("fills") or [])
    return BrokerOrder(
        order_id=payload["order_id"],
        intent=intent,
        status=BrokerOrderStatus(payload["status"]),
        filled_quantity=payload.get("filled_quantity", 0),
        fills=fills,
        rejection_reason=payload.get("rejection_reason"),
        metadata=payload.get("metadata") or {},
    )


def _fill_from_payload(payload: Mapping[str, Any]) -> Fill:
    return Fill(
        fill_id=payload["fill_id"],
        order_id=payload["order_id"],
        symbol=payload["symbol"],
        side=OrderSide(payload["side"]),
        quantity=payload["quantity"],
        price=payload["price"],
        timestamp=payload.get("timestamp"),
        metadata=payload.get("metadata") or {},
    )


def _account_payload(broker: PaperBroker) -> dict[str, Any]:
    account = broker.get_account()
    return {
        "cash": account.cash,
        "total_value": account.total_value,
        "buying_power": account.buying_power,
        "currency": account.currency,
    }


def _positions_payload(broker: PaperBroker) -> list[dict[str, Any]]:
    return [
        {
            "symbol": position.symbol,
            "shares": position.shares,
            "market_value": position.market_value,
            "last_price": position.last_price,
        }
        for position in broker.get_positions()
    ]


def _quote_payload(quote: Quote) -> dict[str, Any]:
    return {
        "symbol": quote.symbol,
        "price": quote.price,
        "bid": quote.bid,
        "ask": quote.ask,
        "timestamp": quote.timestamp,
    }


def _order_payload(order: BrokerOrder) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "symbol": order.symbol,
        "side": order.side.value,
        "shares": order.intent.shares,
        "limit_price": order.intent.limit_price,
        "filled_quantity": order.filled_quantity,
        "remaining_quantity": order.remaining_quantity,
        "rejection_reason": order.rejection_reason,
        "intent": {
            "symbol": order.intent.symbol,
            "side": order.intent.side.value,
            "shares": order.intent.shares,
            "limit_price": order.intent.limit_price,
            "source_action": order.intent.source_action,
            "source_justification": order.intent.source_justification,
            "metadata": dict(order.intent.metadata),
        },
        "fills": [_fill_payload(fill) for fill in order.fills],
        "metadata": dict(order.metadata),
    }


def _fill_payload(fill: Fill) -> dict[str, Any]:
    return {
        "fill_id": fill.fill_id,
        "order_id": fill.order_id,
        "symbol": fill.symbol,
        "side": fill.side.value,
        "quantity": fill.quantity,
        "price": fill.price,
        "notional": fill.notional,
        "timestamp": fill.timestamp,
        "metadata": dict(fill.metadata),
    }


def _resolve_state_path(state_path: str | Path | None) -> Path:
    path = Path(state_path) if state_path is not None else DEFAULT_PAPER_STATE_PATH
    if path.is_absolute():
        return path
    return get_project_root() / path
