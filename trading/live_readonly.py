"""Read-only live broker adapter boundary."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from shared.utils.path_manager import get_project_root


DEFAULT_LIVE_READONLY_PROVIDER = "snapshot"
LIVE_READONLY_PROVIDER_ENV = "QUANTARENA_LIVE_READONLY_PROVIDER"
LIVE_READONLY_SNAPSHOT_ENV = "QUANTARENA_LIVE_READONLY_SNAPSHOT"


class LiveReadonlyError(RuntimeError):
    """Base error for live read-only adapter failures."""


class LiveReadonlyConfigurationError(LiveReadonlyError):
    """Raised when a live read-only adapter cannot be configured."""


class LiveReadonlyMutationError(LiveReadonlyError):
    """Raised when a caller attempts to mutate through a read-only adapter."""


@dataclass(frozen=True)
class LiveReadonlyConfig:
    """Configuration for the live read-only broker adapter."""

    provider: str = DEFAULT_LIVE_READONLY_PROVIDER
    snapshot_path: Path | None = None

    @classmethod
    def from_env(
        cls,
        *,
        provider: str | None = None,
        snapshot_path: str | Path | None = None,
    ) -> "LiveReadonlyConfig":
        resolved_provider = (
            provider
            or os.getenv(LIVE_READONLY_PROVIDER_ENV)
            or DEFAULT_LIVE_READONLY_PROVIDER
        )
        resolved_snapshot = snapshot_path or os.getenv(LIVE_READONLY_SNAPSHOT_ENV)
        return cls(
            provider=str(resolved_provider).strip().lower(),
            snapshot_path=_resolve_snapshot_path(resolved_snapshot),
        )


@dataclass(frozen=True)
class LiveReadonlyCommandResult:
    """JSON-ready live read-only command result."""

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


class SnapshotLiveReadonlyBrokerAdapter:
    """Read broker-neutral snapshots from a local JSON file."""

    provider = "snapshot"

    def __init__(self, snapshot_path: str | Path | None):
        self.snapshot_path = _resolve_snapshot_path(snapshot_path)
        if self.snapshot_path is None:
            raise LiveReadonlyConfigurationError(
                "snapshot provider requires --snapshot or QUANTARENA_LIVE_READONLY_SNAPSHOT"
            )

    def get_account(self) -> dict[str, Any]:
        payload = self._load_payload()
        return _account_payload(payload)

    def get_positions(self) -> list[dict[str, Any]]:
        payload = self._load_payload()
        return _positions_payload(payload)

    def get_orders(
        self,
        *,
        status: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        payload = self._load_payload()
        normalized_status = str(status).strip().lower() if status else None
        normalized_symbol = str(symbol).strip().upper() if symbol else None
        orders = _orders_payload(payload)
        if normalized_status:
            orders = [
                order
                for order in orders
                if str(order.get("status", "")).strip().lower() == normalized_status
            ]
        if normalized_symbol:
            orders = [
                order
                for order in orders
                if str(order.get("symbol", "")).strip().upper() == normalized_symbol
            ]
        return orders

    def get_quotes(self, symbols: Sequence[str] | None = None) -> dict[str, dict[str, Any]]:
        payload = self._load_payload()
        quotes = _quotes_payload(payload)
        requested = [symbol.strip().upper() for symbol in (symbols or []) if symbol.strip()]
        if not requested:
            return quotes
        return {symbol: quotes[symbol] for symbol in requested if symbol in quotes}

    def submit_order(self, *args: Any, **kwargs: Any) -> None:
        raise LiveReadonlyMutationError("live read-only adapter does not allow order submission")

    def fill_order(self, *args: Any, **kwargs: Any) -> None:
        raise LiveReadonlyMutationError("live read-only adapter does not allow order fills")

    def cancel_order(self, *args: Any, **kwargs: Any) -> None:
        raise LiveReadonlyMutationError("live read-only adapter does not allow order cancellation")

    def _load_payload(self) -> Mapping[str, Any]:
        assert self.snapshot_path is not None
        if not self.snapshot_path.is_file():
            raise LiveReadonlyConfigurationError(f"live snapshot not found: {self.snapshot_path}")
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LiveReadonlyConfigurationError(f"invalid live snapshot JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise LiveReadonlyConfigurationError("live snapshot must be a JSON object")
        return payload


class LiveReadonlyBrokerManager:
    """Command-oriented facade over a live read-only broker adapter."""

    def __init__(
        self,
        config: LiveReadonlyConfig | None = None,
        adapter: SnapshotLiveReadonlyBrokerAdapter | None = None,
    ):
        self.config = config or LiveReadonlyConfig.from_env()
        self.adapter = adapter or create_live_readonly_adapter(self.config)

    def account(self) -> LiveReadonlyCommandResult:
        return LiveReadonlyCommandResult(
            ok=True,
            command="account",
            result={"provider": self.adapter.provider, "account": self.adapter.get_account()},
        )

    def positions(self) -> LiveReadonlyCommandResult:
        return LiveReadonlyCommandResult(
            ok=True,
            command="positions",
            result={"provider": self.adapter.provider, "positions": self.adapter.get_positions()},
        )

    def orders(self, *, status: str | None = None, symbol: str | None = None) -> LiveReadonlyCommandResult:
        return LiveReadonlyCommandResult(
            ok=True,
            command="orders",
            result={
                "provider": self.adapter.provider,
                "orders": self.adapter.get_orders(status=status, symbol=symbol),
            },
        )

    def quotes(self, *, symbols: Sequence[str] | None = None) -> LiveReadonlyCommandResult:
        return LiveReadonlyCommandResult(
            ok=True,
            command="quotes",
            result={
                "provider": self.adapter.provider,
                "quotes": self.adapter.get_quotes(symbols),
            },
        )

    def smoke(self) -> LiveReadonlyCommandResult:
        steps: list[dict[str, Any]] = []
        for step in [
            self.account(),
            self.positions(),
            self.orders(),
            self.quotes(symbols=self._smoke_quote_symbols()),
        ]:
            steps.append(step.to_dict())
            if not step.ok:
                break
        ok = all(step.get("ok") is True for step in steps)
        failing_step = next((step for step in steps if step.get("ok") is not True), None)
        return LiveReadonlyCommandResult(
            ok=ok,
            command="smoke",
            result={"provider": self.adapter.provider, "steps": steps},
            error=None if ok else f"live readonly smoke failed at {failing_step.get('command')}",
        )

    def _smoke_quote_symbols(self) -> list[str]:
        quotes = self.adapter.get_quotes()
        if quotes:
            return sorted(quotes)
        positions = self.adapter.get_positions()
        return sorted(
            {
                str(position.get("symbol", "")).strip().upper()
                for position in positions
                if str(position.get("symbol", "")).strip()
            }
        )


def create_live_readonly_adapter(config: LiveReadonlyConfig) -> SnapshotLiveReadonlyBrokerAdapter:
    """Create the configured live read-only adapter."""
    provider = str(config.provider or "").strip().lower()
    if provider == "snapshot":
        return SnapshotLiveReadonlyBrokerAdapter(config.snapshot_path)
    raise LiveReadonlyConfigurationError(f"unsupported live read-only provider: {config.provider}")


def _account_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    account = payload.get("account") if isinstance(payload.get("account"), Mapping) else payload
    cash = _optional_float(account.get("cash"))
    total_value = _optional_float(account.get("total_value"))
    buying_power = _optional_float(account.get("buying_power"))
    if total_value is None and cash is not None:
        position_value = sum(
            float(position.get("market_value") or 0.0)
            for position in _positions_payload(payload)
        )
        total_value = cash + position_value
    if buying_power is None:
        buying_power = cash
    return {
        "cash": cash,
        "total_value": total_value,
        "buying_power": buying_power,
        "currency": str(account.get("currency") or "USD"),
    }


def _positions_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_positions = payload.get("positions") or []
    quotes = _quotes_payload(payload)
    positions: list[dict[str, Any]] = []
    if isinstance(raw_positions, Mapping):
        iterable = [
            {"symbol": symbol, **(position if isinstance(position, Mapping) else {"shares": position})}
            for symbol, position in raw_positions.items()
        ]
    else:
        iterable = raw_positions

    for raw_position in iterable:
        if not isinstance(raw_position, Mapping):
            continue
        symbol = str(raw_position.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        shares = _int_value(raw_position.get("shares"))
        last_price = _optional_float(raw_position.get("last_price"))
        if last_price is None and symbol in quotes:
            last_price = quotes[symbol]["price"]
        market_value = _optional_float(raw_position.get("market_value"))
        if market_value is None and last_price is not None:
            market_value = shares * last_price
        positions.append(
            {
                "symbol": symbol,
                "shares": shares,
                "market_value": market_value,
                "last_price": last_price,
            }
        )
    return sorted(positions, key=lambda item: item["symbol"])


def _orders_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    for raw_order in payload.get("orders") or []:
        if not isinstance(raw_order, Mapping):
            continue
        symbol = str(raw_order.get("symbol", "")).strip().upper()
        orders.append(
            {
                "order_id": raw_order.get("order_id"),
                "status": raw_order.get("status"),
                "symbol": symbol,
                "side": str(raw_order.get("side", "")).strip().upper() or None,
                "shares": _int_value(raw_order.get("shares")),
                "limit_price": _optional_float(raw_order.get("limit_price")),
                "filled_quantity": _int_value(raw_order.get("filled_quantity")),
                "remaining_quantity": _int_value(raw_order.get("remaining_quantity")),
                "rejection_reason": raw_order.get("rejection_reason"),
                "metadata": dict(raw_order.get("metadata") or {}),
            }
        )
    return sorted(orders, key=lambda item: str(item.get("order_id") or ""))


def _quotes_payload(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    raw_quotes = payload.get("quotes") or {}
    if isinstance(raw_quotes, Mapping):
        items = raw_quotes.items()
    else:
        items = [
            (quote.get("symbol"), quote)
            for quote in raw_quotes
            if isinstance(quote, Mapping)
        ]

    for symbol_hint, raw_quote in items:
        if isinstance(raw_quote, Mapping):
            symbol = str(raw_quote.get("symbol") or symbol_hint or "").strip().upper()
            price = _optional_float(raw_quote.get("price"))
            bid = _optional_float(raw_quote.get("bid"))
            ask = _optional_float(raw_quote.get("ask"))
            timestamp = raw_quote.get("timestamp")
        else:
            symbol = str(symbol_hint or "").strip().upper()
            price = _optional_float(raw_quote)
            bid = None
            ask = None
            timestamp = None
        if not symbol:
            continue
        quotes[symbol] = {
            "symbol": symbol,
            "price": price,
            "bid": bid,
            "ask": ask,
            "timestamp": timestamp,
        }
    return dict(sorted(quotes.items()))


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _resolve_snapshot_path(path: str | Path | None) -> Path | None:
    if path is None or str(path).strip() == "":
        return None
    resolved = Path(path)
    if resolved.is_absolute():
        return resolved
    return get_project_root() / resolved
