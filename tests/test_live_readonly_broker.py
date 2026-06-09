"""Tests for the live read-only broker adapter."""

from __future__ import annotations

import json
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


def test_snapshot_live_readonly_adapter_reads_snapshots_and_filters(tmp_path: Path):
    snapshot = _write_live_snapshot(tmp_path / "live_snapshot.json")
    manager = LiveReadonlyBrokerManager(
        config=LiveReadonlyConfig(provider="snapshot", snapshot_path=snapshot)
    )

    account = manager.account()
    positions = manager.positions()
    filled_aapl_orders = manager.orders(status="filled", symbol="AAPL")
    quotes = manager.quotes(symbols=["MSFT", "MISSING"])

    assert account.ok is True
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


def test_live_readonly_manager_smoke_queries_read_paths(tmp_path: Path):
    snapshot = _write_live_snapshot(tmp_path / "live_snapshot.json")
    manager = LiveReadonlyBrokerManager(
        config=LiveReadonlyConfig(provider="snapshot", snapshot_path=snapshot)
    )

    result = manager.smoke()

    assert result.ok is True
    assert [step["command"] for step in result.result["steps"]] == [
        "account",
        "positions",
        "orders",
        "quotes",
    ]
    assert result.result["provider"] == "snapshot"


def test_live_readonly_adapter_rejects_mutations(tmp_path: Path):
    snapshot = _write_live_snapshot(tmp_path / "live_snapshot.json")
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


def _write_live_snapshot(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "account": {
                    "cash": 1200.5,
                    "total_value": 1550.5,
                    "buying_power": 1200.5,
                    "currency": "USD",
                },
                "positions": {
                    "MSFT": {"shares": 1, "market_value": 55.0, "last_price": 55.0},
                    "AAPL": {"shares": 2, "market_value": 200.0, "last_price": 100.0},
                },
                "orders": [
                    {
                        "order_id": "live-002",
                        "status": "open",
                        "symbol": "MSFT",
                        "side": "SELL",
                        "shares": 1,
                        "limit_price": 56.0,
                        "filled_quantity": 0,
                        "remaining_quantity": 1,
                    },
                    {
                        "order_id": "live-001",
                        "status": "filled",
                        "symbol": "AAPL",
                        "side": "BUY",
                        "shares": 2,
                        "limit_price": 100.0,
                        "filled_quantity": 2,
                        "remaining_quantity": 0,
                    },
                ],
                "quotes": {
                    "AAPL": {"price": 101.0, "bid": 100.5, "ask": 101.5, "timestamp": "2026-06-09T00:00:00Z"},
                    "MSFT": 55.0,
                },
            }
        ),
        encoding="utf-8",
    )
    return path
