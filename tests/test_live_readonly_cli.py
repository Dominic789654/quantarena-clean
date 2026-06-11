"""Tests for QuantArena live read-only CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantarena.cli import build_parser, main
from trading import PaperPortfolioManager


FIXTURE_SNAPSHOT = Path("tests/fixtures/live_readonly/snapshot.json")


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


def test_cli_parser_exposes_live_contract_command():
    parser = build_parser()
    args = parser.parse_args(["live", "--snapshot", "live.json", "contract"])

    assert args.command == "live"
    assert args.live_command == "contract"
    assert str(args.snapshot) == "live.json"


def test_cli_parser_exposes_live_paper_sandbox_state():
    parser = build_parser()
    args = parser.parse_args(
        [
            "live",
            "--provider",
            "paper_sandbox",
            "--paper-state",
            "paper.json",
            "account",
        ]
    )

    assert args.command == "live"
    assert args.provider == "paper_sandbox"
    assert str(args.paper_state) == "paper.json"
    assert args.live_command == "account"


def test_cli_parser_does_not_expose_live_mutating_order_commands():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["live", "order", "submit"])


def test_live_cli_account_outputs_json(capsys):
    exit_code = main(["live", "--snapshot", str(FIXTURE_SNAPSHOT), "account"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["command"] == "account"
    assert payload["result"]["provider"] == "snapshot"
    assert payload["result"]["readonly"] is True
    assert payload["result"]["mutation_allowed"] is False
    assert payload["result"]["account"]["total_value"] == 1550.5


def test_live_cli_contract_outputs_provider_contract(capsys):
    exit_code = main(["live", "--snapshot", str(FIXTURE_SNAPSHOT), "contract"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["command"] == "contract"
    assert payload["error"] is None
    assert payload["result"]["provider"] == "snapshot"
    assert payload["result"]["readonly"] is True
    assert payload["result"]["mutation_allowed"] is False
    assert [(check["command"], check["ok"], check["count"]) for check in payload["result"]["checks"]] == [
        ("account", True, 1),
        ("positions", True, 2),
        ("orders", True, 2),
        ("quotes", True, 2),
    ]


def test_live_cli_paper_sandbox_account_and_contract_do_not_mutate_state(tmp_path: Path, capsys):
    state = _write_paper_state(tmp_path / "paper_state.json")
    before = state.read_text(encoding="utf-8")

    account_exit = main(
        [
            "live",
            "--provider",
            "paper_sandbox",
            "--paper-state",
            str(state),
            "account",
        ]
    )
    account_payload = json.loads(capsys.readouterr().out)
    contract_exit = main(
        [
            "live",
            "--provider",
            "paper_sandbox",
            "--paper-state",
            str(state),
            "contract",
        ]
    )
    contract_payload = json.loads(capsys.readouterr().out)

    assert account_exit == 0
    assert account_payload["ok"] is True
    assert account_payload["result"]["provider"] == "paper_sandbox"
    assert account_payload["result"]["paper_state_path"] == str(state)
    assert account_payload["result"]["account"]["cash"] == 700.0
    assert contract_exit == 0
    assert contract_payload["ok"] is True
    assert contract_payload["command"] == "contract"
    assert contract_payload["result"]["provider"] == "paper_sandbox"
    assert state.read_text(encoding="utf-8") == before


def test_live_cli_smoke_outputs_readonly_steps(capsys):
    exit_code = main(["live", "--snapshot", str(FIXTURE_SNAPSHOT), "smoke"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["result"]["readonly"] is True
    assert payload["result"]["mutation_allowed"] is False
    assert payload["result"]["snapshot_path"].endswith("tests/fixtures/live_readonly/snapshot.json")
    assert [(step["command"], step["count"], step["error"]) for step in payload["result"]["steps"]] == [
        ("account", 1, None),
        ("positions", 2, None),
        ("orders", 2, None),
        ("quotes", 2, None),
    ]


def test_live_cli_missing_snapshot_returns_nonzero_json(tmp_path: Path, capsys):
    exit_code = main(["live", "--snapshot", str(tmp_path / "missing.json"), "positions"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["command"] == "positions"
    assert "live snapshot not found" in payload["error"]


def test_live_cli_contract_missing_snapshot_returns_category(tmp_path: Path, capsys):
    exit_code = main(["live", "--snapshot", str(tmp_path / "missing.json"), "contract"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["command"] == "contract"
    assert payload["error"].startswith("live snapshot not found")
    assert payload["result"]["category"] == "credential_missing"
    assert payload["result"]["failed_command"] == "account"


def test_live_cli_paper_sandbox_missing_state_returns_nonzero_json(tmp_path: Path, capsys):
    exit_code = main(
        [
            "live",
            "--provider",
            "paper_sandbox",
            "--paper-state",
            str(tmp_path / "missing.json"),
            "contract",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["command"] == "contract"
    assert payload["result"]["category"] == "credential_missing"
    assert "paper sandbox state not found" in payload["error"]


def _write_paper_state(path: Path) -> Path:
    result = PaperPortfolioManager(state_path=path).smoke()
    assert result.ok is True
    return path
