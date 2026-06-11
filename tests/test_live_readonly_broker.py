"""Tests for the live read-only broker adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from trading import (
    LiveReadonlyCredentialError,
    LiveReadonlyBrokerManager,
    LiveReadonlyConfig,
    LiveReadonlyConfigurationError,
    LiveReadonlyMutationError,
    LiveReadonlyRateLimitError,
    SnapshotLiveReadonlyBrokerAdapter,
    create_live_readonly_adapter,
    validate_live_readonly_provider_contract,
)


FIXTURE_SNAPSHOT = Path("tests/fixtures/live_readonly/snapshot.json")


def test_snapshot_live_readonly_adapter_reads_snapshots_and_filters():
    snapshot = FIXTURE_SNAPSHOT
    manager = LiveReadonlyBrokerManager(
        config=LiveReadonlyConfig(provider="snapshot", snapshot_path=snapshot)
    )

    account = manager.account()
    positions = manager.positions()
    filled_aapl_orders = manager.orders(status="filled", symbol="AAPL")
    quotes = manager.quotes(symbols=["MSFT", "MISSING"])

    assert account.ok is True
    assert account.result["readonly"] is True
    assert account.result["mutation_allowed"] is False
    assert account.result["snapshot_path"].endswith("tests/fixtures/live_readonly/snapshot.json")
    assert account.result["account"]["cash"] == 1200.5
    assert account.result["account"]["currency"] == "USD"
    assert [position["symbol"] for position in positions.result["positions"]] == ["AAPL", "MSFT"]
    assert filled_aapl_orders.result["orders"][0]["order_id"] == "live-001"
    assert len(filled_aapl_orders.result["orders"]) == 1
    assert quotes.result["quotes"] == {
        "MSFT": {
            "symbol": "MSFT",
            "price": 55.0,
            "bid": None,
            "ask": None,
            "timestamp": None,
        }
    }


def test_live_readonly_manager_smoke_queries_read_paths_with_metadata():
    snapshot = FIXTURE_SNAPSHOT
    manager = LiveReadonlyBrokerManager(
        config=LiveReadonlyConfig(provider="snapshot", snapshot_path=snapshot)
    )

    result = manager.smoke()

    assert result.ok is True
    assert result.result["provider"] == "snapshot"
    assert result.result["readonly"] is True
    assert result.result["mutation_allowed"] is False
    assert result.result["read_operations"] == ["account", "positions", "orders", "quotes"]
    assert result.result["snapshot_path"].endswith("tests/fixtures/live_readonly/snapshot.json")
    assert [(step["command"], step["count"], step["error"]) for step in result.result["steps"]] == [
        ("account", 1, None),
        ("positions", 2, None),
        ("orders", 2, None),
        ("quotes", 2, None),
    ]


def test_live_readonly_manager_smoke_reports_read_failures(tmp_path: Path):
    snapshot = tmp_path / "invalid_snapshot.json"
    snapshot.write_text("[", encoding="utf-8")
    manager = LiveReadonlyBrokerManager(
        config=LiveReadonlyConfig(provider="snapshot", snapshot_path=snapshot)
    )

    result = manager.smoke()

    assert result.ok is False
    assert result.result["readonly"] is True
    assert result.result["mutation_allowed"] is False
    assert result.result["failed_command"] == "account"
    assert result.result["steps"] == [
        {
            "ok": False,
            "command": "account",
            "count": 0,
            "error": result.result["steps"][0]["error"],
        }
    ]
    assert "invalid live snapshot JSON" in result.result["steps"][0]["error"]
    assert "live readonly smoke failed at account" in result.error


def test_live_readonly_manager_exposes_capabilities_without_mutation_facade():
    manager = LiveReadonlyBrokerManager(
        config=LiveReadonlyConfig(provider="snapshot", snapshot_path=FIXTURE_SNAPSHOT)
    )

    assert manager.readonly_capabilities() == {
        "provider": "snapshot",
        "readonly": True,
        "mutation_allowed": False,
        "read_operations": ["account", "positions", "orders", "quotes"],
        "snapshot_path": str(FIXTURE_SNAPSHOT.resolve()),
    }
    assert [operation for operation in ["submit_order", "fill_order", "cancel_order"] if hasattr(manager, operation)] == []
    assert [
        step["command"]
        for step in manager.smoke().result["steps"]
    ] == [
        "account",
        "positions",
        "orders",
        "quotes",
    ]


def test_live_readonly_provider_contract_succeeds_for_snapshot_fixture():
    adapter = SnapshotLiveReadonlyBrokerAdapter(FIXTURE_SNAPSHOT)

    result = validate_live_readonly_provider_contract(adapter)

    assert result.ok is True
    assert result.provider == "snapshot"
    assert result.readonly is True
    assert result.mutation_allowed is False
    assert result.category is None
    assert [(check["command"], check["ok"], check["count"], check["category"]) for check in result.checks] == [
        ("account", True, 1, None),
        ("positions", True, 2, None),
        ("orders", True, 2, None),
        ("quotes", True, 2, None),
    ]


def test_live_readonly_manager_contract_returns_command_result():
    manager = LiveReadonlyBrokerManager(
        config=LiveReadonlyConfig(provider="snapshot", snapshot_path=FIXTURE_SNAPSHOT)
    )

    result = manager.contract()

    assert result.ok is True
    assert result.command == "contract"
    assert result.error is None
    assert result.result["provider"] == "snapshot"
    assert result.result["readonly"] is True
    assert result.result["mutation_allowed"] is False
    assert [check["command"] for check in result.result["checks"]] == [
        "account",
        "positions",
        "orders",
        "quotes",
    ]


def test_live_readonly_provider_contract_reports_schema_failure():
    adapter = _ContractProbeAdapter(account={"cash": 100.0})

    result = validate_live_readonly_provider_contract(adapter)

    assert result.ok is False
    assert result.category == "schema_error"
    assert result.failed_command == "account"
    assert "account.total_value is required" in result.error
    assert result.checks[0]["issues"] == [
        "account.total_value is required",
        "account.buying_power is required",
        "account.currency is required",
    ]


def test_live_readonly_provider_contract_reports_credential_failure():
    adapter = _ContractProbeAdapter(account_error=LiveReadonlyCredentialError("missing BROKER_API_KEY"))

    result = validate_live_readonly_provider_contract(adapter)

    assert result.ok is False
    assert result.category == "credential_missing"
    assert result.failed_command == "account"
    assert result.error == "missing BROKER_API_KEY"


def test_live_readonly_provider_contract_reports_rate_limit_failure():
    adapter = _ContractProbeAdapter(positions_error=LiveReadonlyRateLimitError("provider rate limit exceeded"))

    result = validate_live_readonly_provider_contract(adapter)

    assert result.ok is False
    assert result.category == "rate_limited"
    assert result.failed_command == "positions"
    assert result.error == "provider rate limit exceeded"
    assert [check["command"] for check in result.checks] == ["account", "positions"]


def test_live_readonly_adapter_rejects_mutations():
    snapshot = FIXTURE_SNAPSHOT
    adapter = SnapshotLiveReadonlyBrokerAdapter(snapshot)

    with pytest.raises(LiveReadonlyMutationError):
        adapter.submit_order(symbol="AAPL", side="BUY", shares=1, limit_price=100.0)

    with pytest.raises(LiveReadonlyMutationError):
        adapter.fill_order("live-001")

    with pytest.raises(LiveReadonlyMutationError):
        adapter.cancel_order("live-001")


def test_live_readonly_configuration_errors_are_explicit(tmp_path: Path):
    with pytest.raises(LiveReadonlyConfigurationError, match="requires --snapshot"):
        SnapshotLiveReadonlyBrokerAdapter(None)

    with pytest.raises(LiveReadonlyConfigurationError, match="unsupported"):
        create_live_readonly_adapter(LiveReadonlyConfig(provider="unknown", snapshot_path=tmp_path / "x.json"))


class _ContractProbeAdapter:
    provider = "probe"

    def __init__(
        self,
        *,
        account: dict | None = None,
        account_error: Exception | None = None,
        positions_error: Exception | None = None,
    ):
        self._account = account or {
            "cash": 100.0,
            "total_value": 125.0,
            "buying_power": 100.0,
            "currency": "USD",
        }
        self._account_error = account_error
        self._positions_error = positions_error

    def readonly_capabilities(self) -> dict:
        return {
            "provider": self.provider,
            "readonly": True,
            "mutation_allowed": False,
            "read_operations": ["account", "positions", "orders", "quotes"],
        }

    def get_account(self) -> dict:
        if self._account_error:
            raise self._account_error
        return self._account

    def get_positions(self) -> list[dict]:
        if self._positions_error:
            raise self._positions_error
        return [{"symbol": "AAPL", "shares": 1, "market_value": 101.0, "last_price": 101.0}]

    def get_orders(self) -> list[dict]:
        return [
            {
                "order_id": "probe-001",
                "status": "filled",
                "symbol": "AAPL",
                "side": "BUY",
                "shares": 1,
                "filled_quantity": 1,
                "remaining_quantity": 0,
            }
        ]

    def get_quotes(self) -> dict[str, dict]:
        return {"AAPL": {"symbol": "AAPL", "price": 101.0}}
