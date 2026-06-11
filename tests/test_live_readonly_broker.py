"""Tests for the live read-only broker adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from trading import (
    LiveReadonlyBrokerManager,
    LiveReadonlyConfig,
    LiveReadonlyConfigurationError,
    LiveReadonlyMutationError,
    SnapshotLiveReadonlyBrokerAdapter,
    create_live_readonly_adapter,
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
