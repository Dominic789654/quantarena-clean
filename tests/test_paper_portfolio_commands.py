"""Tests for persistent paper portfolio command interface."""

from __future__ import annotations

import json
from pathlib import Path

from quantarena.cli import main
from trading.paper_portfolio import PaperPortfolioManager


def test_paper_portfolio_manager_persists_quote_order_fill_and_reconcile(tmp_path: Path):
    state_path = tmp_path / "paper_state.json"
    manager = PaperPortfolioManager(state_path)

    init = manager.init(initial_cash=1000.0)
    quote = manager.set_quote(symbol="AAPL", price=100.0)
    submit = manager.submit_order(symbol="AAPL", side="BUY", shares=3, limit_price=100.0)
    order_id = submit.result["order"]["order_id"]
    fill = manager.fill_order(order_id=order_id, quantity=2, price=100.0)

    reloaded = PaperPortfolioManager(state_path)
    account = reloaded.account()
    positions = reloaded.positions()
    orders = reloaded.orders()
    quotes = reloaded.quotes(symbols=["AAPL"])
    reconcile = reloaded.reconcile(expected_cash=800.0, expected_positions={"AAPL": 2})

    assert init.ok is True
    assert quote.result["quote"]["price"] == 100.0
    assert submit.ok is True
    assert fill.ok is True
    assert fill.result["order"]["status"] == "partial_filled"
    assert account.result["account"]["cash"] == 800.0
    assert positions.result["positions"][0]["shares"] == 2
    assert orders.result["orders"][0]["remaining_quantity"] == 1
    assert quotes.result["quotes"]["AAPL"]["price"] == 100.0
    assert reconcile.ok is True


def test_paper_portfolio_manager_reports_reconciliation_difference(tmp_path: Path):
    manager = PaperPortfolioManager(tmp_path / "paper_state.json")
    manager.init(initial_cash=1000.0)

    result = manager.reconcile(expected_cash=999.0, expected_positions={"MSFT": 1})

    assert result.ok is False
    assert result.error == "reconciliation differences found"
    assert {item["kind"] for item in result.result["differences"]} == {"cash", "position"}


def test_paper_portfolio_reload_preserves_order_and_fill_id_sequences(tmp_path: Path):
    state_path = tmp_path / "paper_state.json"
    manager = PaperPortfolioManager(state_path)
    manager.init(initial_cash=1000.0)
    first = manager.submit_order(symbol="AAPL", side="BUY", shares=2, limit_price=100.0)
    first_order_id = first.result["order"]["order_id"]
    first_fill = manager.fill_order(order_id=first_order_id, quantity=1, price=100.0)

    reloaded = PaperPortfolioManager(state_path)
    second = reloaded.submit_order(symbol="MSFT", side="BUY", shares=1, limit_price=50.0)
    second_fill = reloaded.fill_order(
        order_id=second.result["order"]["order_id"],
        quantity=1,
        price=50.0,
    )

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert first_order_id == "paper-000001"
    assert first_fill.result["fill"]["fill_id"] == "fill-000001"
    assert second.result["order"]["order_id"] == "paper-000002"
    assert second_fill.result["fill"]["fill_id"] == "fill-000002"
    assert payload["next_order_sequence"] == 3
    assert payload["next_fill_sequence"] == 3


def test_paper_portfolio_legacy_state_derives_next_sequences(tmp_path: Path):
    state_path = tmp_path / "legacy_paper_state.json"
    manager = PaperPortfolioManager(state_path)
    manager.init(initial_cash=1000.0)
    first = manager.submit_order(symbol="AAPL", side="BUY", shares=1, limit_price=100.0)
    manager.fill_order(order_id=first.result["order"]["order_id"], quantity=1, price=100.0)
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload.pop("next_order_sequence")
    payload.pop("next_fill_sequence")
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    reloaded = PaperPortfolioManager(state_path)
    second = reloaded.submit_order(symbol="MSFT", side="BUY", shares=1, limit_price=50.0)
    second_fill = reloaded.fill_order(order_id=second.result["order"]["order_id"])

    assert second.result["order"]["order_id"] == "paper-000002"
    assert second_fill.result["fill"]["fill_id"] == "fill-000002"


def test_paper_portfolio_manager_smoke_runs_lifecycle(tmp_path: Path):
    state_path = tmp_path / "paper_smoke.json"
    manager = PaperPortfolioManager(state_path)

    result = manager.smoke()

    commands = [step["command"] for step in result.result["steps"]]
    assert result.ok is True
    assert commands == [
        "init",
        "quote.set",
        "order.submit",
        "order.fill",
        "account",
        "positions",
        "orders",
        "quotes",
        "reconcile",
    ]
    assert state_path.is_file()
    assert result.result["steps"][-1]["ok"] is True


def test_paper_cli_end_to_end_json_payloads(tmp_path: Path, capsys):
    state = tmp_path / "paper.json"

    assert main(["paper", "--state", str(state), "init", "--cash", "1000"]) == 0
    assert main(["paper", "--state", str(state), "quote", "set", "AAPL", "100"]) == 0
    assert (
        main(
            [
                "paper",
                "--state",
                str(state),
                "order",
                "submit",
                "--symbol",
                "AAPL",
                "--side",
                "BUY",
                "--shares",
                "3",
                "--limit",
                "100",
            ]
        )
        == 0
    )
    output_lines = capsys.readouterr().out.strip().splitlines()
    submit_payload = json.loads(output_lines[-1])
    order_id = submit_payload["result"]["order"]["order_id"]

    assert main(["paper", "--state", str(state), "order", "fill", order_id, "--qty", "3"]) == 0
    assert main(["paper", "--state", str(state), "account"]) == 0
    assert main(["paper", "--state", str(state), "positions"]) == 0
    assert main(["paper", "--state", str(state), "orders", "--symbol", "AAPL"]) == 0
    assert (
        main(
            [
                "paper",
                "--state",
                str(state),
                "reconcile",
                "--cash",
                "700",
                "--position",
                "AAPL:3",
            ]
        )
        == 0
    )

    payloads = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert payloads[-1]["ok"] is True
    assert payloads[-1]["command"] == "reconcile"
    assert payloads[-2]["result"]["orders"][0]["status"] == "filled"


def test_paper_cli_smoke_returns_json_payload(tmp_path: Path, capsys):
    state = tmp_path / "paper_smoke.json"

    exit_code = main(["paper", "--state", str(state), "smoke"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["command"] == "smoke"
    assert payload["result"]["steps"][-1]["command"] == "reconcile"
    assert state.is_file()


def test_paper_cli_failure_returns_nonzero_json(tmp_path: Path, capsys):
    state = tmp_path / "missing.json"

    exit_code = main(["paper", "--state", str(state), "account"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["command"] == "account"
    assert "state not found" in payload["error"]
