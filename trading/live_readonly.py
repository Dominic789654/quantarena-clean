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
LIVE_READONLY_PAPER_STATE_ENV = "QUANTARENA_LIVE_READONLY_PAPER_STATE"
LIVE_READONLY_READ_OPERATIONS = ("account", "positions", "orders", "quotes")
LIVE_READONLY_ERROR_CREDENTIAL_MISSING = "credential_missing"
LIVE_READONLY_ERROR_PROVIDER = "provider_error"
LIVE_READONLY_ERROR_RATE_LIMITED = "rate_limited"
LIVE_READONLY_ERROR_SCHEMA = "schema_error"


class LiveReadonlyError(RuntimeError):
    """Base error for live read-only adapter failures."""


class LiveReadonlyConfigurationError(LiveReadonlyError):
    """Raised when a live read-only adapter cannot be configured."""


class LiveReadonlyMutationError(LiveReadonlyError):
    """Raised when a caller attempts to mutate through a read-only adapter."""


class LiveReadonlyCredentialError(LiveReadonlyError):
    """Raised when a provider is missing required credentials."""


class LiveReadonlyRateLimitError(LiveReadonlyError):
    """Raised when a provider rate limit blocks a read operation."""


@dataclass(frozen=True)
class LiveReadonlyConfig:
    """Configuration for the live read-only broker adapter."""

    provider: str = DEFAULT_LIVE_READONLY_PROVIDER
    snapshot_path: Path | None = None
    paper_state_path: Path | None = None

    @classmethod
    def from_env(
        cls,
        *,
        provider: str | None = None,
        snapshot_path: str | Path | None = None,
        paper_state_path: str | Path | None = None,
    ) -> "LiveReadonlyConfig":
        resolved_provider = (
            provider
            or os.getenv(LIVE_READONLY_PROVIDER_ENV)
            or DEFAULT_LIVE_READONLY_PROVIDER
        )
        resolved_snapshot = snapshot_path or os.getenv(LIVE_READONLY_SNAPSHOT_ENV)
        resolved_paper_state = paper_state_path or os.getenv(LIVE_READONLY_PAPER_STATE_ENV)
        return cls(
            provider=str(resolved_provider).strip().lower(),
            snapshot_path=_resolve_snapshot_path(resolved_snapshot),
            paper_state_path=_resolve_project_path(resolved_paper_state),
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


@dataclass(frozen=True)
class LiveReadonlyProviderContractResult:
    """JSON-ready provider contract validation result."""

    ok: bool
    provider: str
    readonly: bool
    mutation_allowed: bool
    checks: list[dict[str, Any]]
    category: str | None = None
    failed_command: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "provider": self.provider,
            "readonly": self.readonly,
            "mutation_allowed": self.mutation_allowed,
            "checks": self.checks,
            "category": self.category,
            "failed_command": self.failed_command,
            "error": self.error,
        }
        return payload


class SnapshotLiveReadonlyBrokerAdapter:
    """Read broker-neutral snapshots from a local JSON file."""

    provider = "snapshot"
    readonly = True
    mutation_allowed = False

    def __init__(self, snapshot_path: str | Path | None):
        self.snapshot_path = _resolve_snapshot_path(snapshot_path)
        if self.snapshot_path is None:
            raise LiveReadonlyConfigurationError(
                "snapshot provider requires --snapshot or QUANTARENA_LIVE_READONLY_SNAPSHOT"
            )

    def readonly_capabilities(self) -> dict[str, Any]:
        return _readonly_capabilities(
            provider=self.provider,
            snapshot_path=self.snapshot_path,
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


class PaperSandboxLiveReadonlyBrokerAdapter:
    """Read live-style snapshots from a local paper portfolio state file."""

    provider = "paper_sandbox"
    readonly = True
    mutation_allowed = False

    def __init__(self, paper_state_path: str | Path | None):
        self.paper_state_path = _resolve_project_path(paper_state_path)
        if self.paper_state_path is None:
            raise LiveReadonlyConfigurationError(
                "paper_sandbox provider requires --paper-state or QUANTARENA_LIVE_READONLY_PAPER_STATE"
            )

    def readonly_capabilities(self) -> dict[str, Any]:
        return _readonly_capabilities(
            provider=self.provider,
            paper_state_path=self.paper_state_path,
        )

    def get_account(self) -> dict[str, Any]:
        from .paper_portfolio import _account_payload

        return _account_payload(self._load_broker())

    def get_positions(self) -> list[dict[str, Any]]:
        from .paper_portfolio import _positions_payload

        return _positions_payload(self._load_broker())

    def get_orders(
        self,
        *,
        status: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        from .broker import BrokerOrderStatus
        from .paper_portfolio import _order_payload

        broker = self._load_broker()
        normalized_status = BrokerOrderStatus(status) if status else None
        return [
            _order_payload(order)
            for order in broker.get_orders(status=normalized_status, symbol=symbol)
        ]

    def get_quotes(self, symbols: Sequence[str] | None = None) -> dict[str, dict[str, Any]]:
        from .paper_portfolio import _quote_payload

        broker = self._load_broker()
        requested = [symbol.strip().upper() for symbol in (symbols or []) if symbol.strip()]
        if not requested:
            requested = sorted(broker.quotes)
        return {
            symbol: _quote_payload(quote)
            for symbol, quote in broker.get_quotes(requested).items()
        }

    def submit_order(self, *args: Any, **kwargs: Any) -> None:
        raise LiveReadonlyMutationError("paper_sandbox live read-only adapter does not allow order submission")

    def fill_order(self, *args: Any, **kwargs: Any) -> None:
        raise LiveReadonlyMutationError("paper_sandbox live read-only adapter does not allow order fills")

    def cancel_order(self, *args: Any, **kwargs: Any) -> None:
        raise LiveReadonlyMutationError("paper_sandbox live read-only adapter does not allow order cancellation")

    def _load_broker(self) -> Any:
        from .paper_portfolio import broker_from_state

        assert self.paper_state_path is not None
        if not self.paper_state_path.is_file():
            raise LiveReadonlyConfigurationError(f"paper sandbox state not found: {self.paper_state_path}")
        try:
            payload = json.loads(self.paper_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LiveReadonlyConfigurationError(f"invalid paper sandbox state JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise LiveReadonlyConfigurationError("paper sandbox state must be a JSON object")
        return broker_from_state(payload)


class LiveReadonlyBrokerManager:
    """Command-oriented facade over a live read-only broker adapter."""

    def __init__(
        self,
        config: LiveReadonlyConfig | None = None,
        adapter: Any | None = None,
    ):
        self.config = config or LiveReadonlyConfig.from_env()
        self.adapter = adapter or create_live_readonly_adapter(self.config)

    def readonly_capabilities(self) -> dict[str, Any]:
        if hasattr(self.adapter, "readonly_capabilities"):
            capabilities = self.adapter.readonly_capabilities()
        else:
            capabilities = _readonly_capabilities(
                provider=getattr(self.adapter, "provider", self.config.provider),
                snapshot_path=getattr(self.adapter, "snapshot_path", None),
                paper_state_path=getattr(self.adapter, "paper_state_path", None),
            )
        return dict(capabilities)

    def account(self) -> LiveReadonlyCommandResult:
        return LiveReadonlyCommandResult(
            ok=True,
            command="account",
            result={**self.readonly_capabilities(), "account": self.adapter.get_account()},
        )

    def positions(self) -> LiveReadonlyCommandResult:
        return LiveReadonlyCommandResult(
            ok=True,
            command="positions",
            result={**self.readonly_capabilities(), "positions": self.adapter.get_positions()},
        )

    def orders(self, *, status: str | None = None, symbol: str | None = None) -> LiveReadonlyCommandResult:
        return LiveReadonlyCommandResult(
            ok=True,
            command="orders",
            result={
                **self.readonly_capabilities(),
                "orders": self.adapter.get_orders(status=status, symbol=symbol),
            },
        )

    def quotes(self, *, symbols: Sequence[str] | None = None) -> LiveReadonlyCommandResult:
        return LiveReadonlyCommandResult(
            ok=True,
            command="quotes",
            result={
                **self.readonly_capabilities(),
                "quotes": self.adapter.get_quotes(symbols),
            },
        )

    def smoke(self) -> LiveReadonlyCommandResult:
        steps: list[dict[str, Any]] = []
        checks = [
            ("account", self.adapter.get_account),
            ("positions", self.adapter.get_positions),
            ("orders", self.adapter.get_orders),
            ("quotes", self.adapter.get_quotes),
        ]
        for command, read_fn in checks:
            step = _run_smoke_step(command, read_fn)
            steps.append(step)
            if not step["ok"]:
                break
        ok = all(step.get("ok") is True for step in steps)
        failing_step = next((step for step in steps if step.get("ok") is not True), None)
        result = {**self.readonly_capabilities(), "steps": steps}
        if failing_step:
            result["failed_command"] = failing_step.get("command")
        return LiveReadonlyCommandResult(
            ok=ok,
            command="smoke",
            result=result,
            error=(
                None
                if ok
                else f"live readonly smoke failed at {failing_step.get('command')}: {failing_step.get('error')}"
            ),
        )

    def contract(self) -> LiveReadonlyCommandResult:
        contract_result = validate_live_readonly_provider_contract(self.adapter)
        return LiveReadonlyCommandResult(
            ok=contract_result.ok,
            command="contract",
            result={**self.readonly_capabilities(), **contract_result.to_dict()},
            error=contract_result.error,
        )


def create_live_readonly_adapter(
    config: LiveReadonlyConfig,
) -> SnapshotLiveReadonlyBrokerAdapter | PaperSandboxLiveReadonlyBrokerAdapter:
    """Create the configured live read-only adapter."""
    provider = str(config.provider or "").strip().lower()
    if provider == "snapshot":
        return SnapshotLiveReadonlyBrokerAdapter(config.snapshot_path)
    if provider == "paper_sandbox":
        return PaperSandboxLiveReadonlyBrokerAdapter(config.paper_state_path)
    raise LiveReadonlyConfigurationError(f"unsupported live read-only provider: {config.provider}")


def validate_live_readonly_provider_contract(adapter: Any) -> LiveReadonlyProviderContractResult:
    """Validate a live read-only provider against the broker-neutral read contract."""
    capabilities = (
        adapter.readonly_capabilities()
        if hasattr(adapter, "readonly_capabilities")
        else _readonly_capabilities(
            provider=getattr(adapter, "provider", "unknown"),
            snapshot_path=getattr(adapter, "snapshot_path", None),
            paper_state_path=getattr(adapter, "paper_state_path", None),
        )
    )
    provider = str(capabilities.get("provider") or getattr(adapter, "provider", "unknown"))
    readonly = bool(capabilities.get("readonly") is True)
    mutation_allowed = bool(capabilities.get("mutation_allowed") is True)
    checks: list[dict[str, Any]] = []
    read_plan = [
        ("account", adapter.get_account),
        ("positions", adapter.get_positions),
        ("orders", adapter.get_orders),
        ("quotes", adapter.get_quotes),
    ]
    for command, read_fn in read_plan:
        check = _validate_provider_contract_read(command, read_fn)
        checks.append(check)
        if not check["ok"]:
            return LiveReadonlyProviderContractResult(
                ok=False,
                provider=provider,
                readonly=readonly,
                mutation_allowed=mutation_allowed,
                checks=checks,
                category=check["category"],
                failed_command=command,
                error=check["error"],
            )

    capability_issues = _validate_contract_capabilities(capabilities)
    if capability_issues:
        checks.append(
            {
                "ok": False,
                "command": "capabilities",
                "category": LIVE_READONLY_ERROR_SCHEMA,
                "count": 0,
                "issues": capability_issues,
                "error": "; ".join(capability_issues),
            }
        )
        return LiveReadonlyProviderContractResult(
            ok=False,
            provider=provider,
            readonly=readonly,
            mutation_allowed=mutation_allowed,
            checks=checks,
            category=LIVE_READONLY_ERROR_SCHEMA,
            failed_command="capabilities",
            error="; ".join(capability_issues),
        )

    return LiveReadonlyProviderContractResult(
        ok=True,
        provider=provider,
        readonly=readonly,
        mutation_allowed=mutation_allowed,
        checks=checks,
    )


def _readonly_capabilities(
    *,
    provider: str,
    snapshot_path: str | Path | None = None,
    paper_state_path: str | Path | None = None,
) -> dict[str, Any]:
    capabilities = {
        "provider": provider,
        "readonly": True,
        "mutation_allowed": False,
        "read_operations": list(LIVE_READONLY_READ_OPERATIONS),
    }
    if snapshot_path is not None:
        capabilities["snapshot_path"] = str(snapshot_path)
    if paper_state_path is not None:
        capabilities["paper_state_path"] = str(paper_state_path)
    return capabilities


def _validate_provider_contract_read(command: str, read_fn: Any) -> dict[str, Any]:
    try:
        payload = read_fn()
    except Exception as exc:
        category = _live_readonly_error_category(exc)
        return {
            "ok": False,
            "command": command,
            "category": category,
            "count": 0,
            "issues": [],
            "error": str(exc),
        }
    issues = _validate_contract_payload(command, payload)
    return {
        "ok": not issues,
        "command": command,
        "category": None if not issues else LIVE_READONLY_ERROR_SCHEMA,
        "count": _read_result_count(command, payload),
        "issues": issues,
        "error": None if not issues else "; ".join(issues),
    }


def _live_readonly_error_category(exc: Exception) -> str:
    if isinstance(exc, LiveReadonlyCredentialError):
        return LIVE_READONLY_ERROR_CREDENTIAL_MISSING
    if isinstance(exc, LiveReadonlyRateLimitError):
        return LIVE_READONLY_ERROR_RATE_LIMITED
    if isinstance(exc, LiveReadonlyConfigurationError):
        return LIVE_READONLY_ERROR_CREDENTIAL_MISSING
    return LIVE_READONLY_ERROR_PROVIDER


def _validate_contract_capabilities(capabilities: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if capabilities.get("readonly") is not True:
        issues.append("capabilities.readonly must be true")
    if capabilities.get("mutation_allowed") is not False:
        issues.append("capabilities.mutation_allowed must be false")
    operations = capabilities.get("read_operations")
    if list(operations or []) != list(LIVE_READONLY_READ_OPERATIONS):
        issues.append("capabilities.read_operations must list account, positions, orders, quotes")
    return issues


def _validate_contract_payload(command: str, payload: Any) -> list[str]:
    if command == "account":
        return _validate_mapping_fields(
            "account",
            payload,
            {
                "cash": (int, float),
                "total_value": (int, float),
                "buying_power": (int, float),
                "currency": str,
            },
        )
    if command == "positions":
        return _validate_list_of_mappings(
            "positions",
            payload,
            {
                "symbol": str,
                "shares": int,
                "market_value": (int, float),
                "last_price": (int, float),
            },
        )
    if command == "orders":
        return _validate_list_of_mappings(
            "orders",
            payload,
            {
                "order_id": object,
                "status": object,
                "symbol": str,
                "side": object,
                "shares": int,
                "filled_quantity": int,
                "remaining_quantity": int,
            },
        )
    if command == "quotes":
        issues: list[str] = []
        if not isinstance(payload, Mapping):
            return ["quotes must be an object keyed by symbol"]
        for symbol, quote in payload.items():
            quote_path = f"quotes.{symbol}"
            issues.extend(
                _validate_mapping_fields(
                    quote_path,
                    quote,
                    {
                        "symbol": str,
                        "price": (int, float),
                    },
                )
            )
        return issues
    return [f"unsupported contract command: {command}"]


def _validate_mapping_fields(
    path: str,
    payload: Any,
    fields: Mapping[str, type | tuple[type, ...]],
) -> list[str]:
    if not isinstance(payload, Mapping):
        return [f"{path} must be an object"]
    issues: list[str] = []
    for field, expected_type in fields.items():
        if field not in payload:
            issues.append(f"{path}.{field} is required")
            continue
        value = payload[field]
        if value is None:
            issues.append(f"{path}.{field} must not be null")
            continue
        if expected_type is object:
            continue
        if not isinstance(value, expected_type):
            issues.append(f"{path}.{field} has invalid type")
    return issues


def _validate_list_of_mappings(
    path: str,
    payload: Any,
    fields: Mapping[str, type | tuple[type, ...]],
) -> list[str]:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, bytearray)):
        return [f"{path} must be a list"]
    issues: list[str] = []
    for index, item in enumerate(payload):
        issues.extend(_validate_mapping_fields(f"{path}[{index}]", item, fields))
    return issues


def _run_smoke_step(command: str, read_fn: Any) -> dict[str, Any]:
    try:
        payload = read_fn()
    except Exception as exc:
        return {
            "ok": False,
            "command": command,
            "count": 0,
            "error": str(exc),
        }
    return {
        "ok": True,
        "command": command,
        "count": _read_result_count(command, payload),
        "error": None,
    }


def _read_result_count(command: str, payload: Any) -> int:
    if command == "account":
        return 1 if isinstance(payload, Mapping) and payload else 0
    if isinstance(payload, Mapping):
        return len(payload)
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return len(payload)
    return 0


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
    return _resolve_project_path(path)


def _resolve_project_path(path: str | Path | None) -> Path | None:
    if path is None or str(path).strip() == "":
        return None
    resolved = Path(path)
    if resolved.is_absolute():
        return resolved
    return get_project_root() / resolved
