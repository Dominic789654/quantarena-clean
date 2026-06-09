"""Tests for QuantArena live read-only CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantarena.cli import build_parser, main


def test_cli_parser_exposes_live_readonly_commands():
    parser = build_parser()
    args = parser.parse_args(
        [
            "live",
            "--provider",
            "snapshot",
            "--snapshot",
            "live.json",
            "orders",
            "--status",
            "filled",
            "--symbol",
            "AAPL",
        ]
    )

    assert args.command == "live"
    assert args.provider == "snapshot"
    assert str(args.snapshot) == "live.json"
    assert args.live_command == "orders"
    assert args.status == "filled"
    assert args.symbol == "AAPL"


def test_cli_parser_does_not_expose_live_mutating_order_commands():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["live", "order", "submit"])


def test_live_cli_account_outputs_json(tmp_path: Path, capsys):
    snapshot = _write_live_snapshot(tmp_path / "live_snapshot.json")

    exit_code = main(["live", "--snapshot", str(snapshot), "account"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["command"] == "account"
    assert payload["result"]["provider"] == "snapshot"
    assert payload["result"]["account"]["total_value"] == 1500.0


def test_live_cli_smoke_outputs_readonly_steps(tmp_path: Path, capsys):
    snapshot = _write_live_snapshot(tmp_path / "live_snapshot.json")

    exit_code = main(["live", "--snapshot", str(snapshot), "smoke"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert [step["command"] for step in payload["result"]["steps"]] == [
        "account",
        "positions",
        "orders",
        "quotes",
    ]


def test_live_cli_missing_snapshot_returns_nonzero_json(tmp_path: Path, capsys):
    exit_code = main(["live", "--snapshot", str(tmp_path / "missing.json"), "positions"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["command"] == "positions"
    assert "live snapshot not found" in payload["error"]


def _write_live_snapshot(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "account": {
                    "cash": 1000.0,
                    "total_value": 1500.0,
                    "buying_power": 1000.0,
                    "currency": "USD",
                },
                "positions": [{"symbol": "AAPL", "shares": 3, "market_value": 300.0, "last_price": 100.0}],
                "orders": [{"order_id": "live-001", "status": "filled", "symbol": "AAPL", "side": "BUY"}],
                "quotes": {"AAPL": {"price": 100.0}},
            }
        ),
        encoding="utf-8",
    )
    return path
