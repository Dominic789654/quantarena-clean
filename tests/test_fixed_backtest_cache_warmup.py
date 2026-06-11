"""Tests for fixed backtest cache warmup planning."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from quantarena.cache_health import FixedBacktestCacheHealthConfig
from quantarena.cli import build_parser, main
from quantarena.fixed_backtest_cache_warmup import build_fixed_backtest_cache_warmup_plan


def test_fixed_cache_warmup_ready_plan_has_no_actions(tmp_path: Path):
    config = _write_ready_cache_config(tmp_path)

    plan = build_fixed_backtest_cache_warmup_plan(config)
    payload = plan.to_dict()

    assert plan.ok is True
    assert payload["dry_run"] is True
    assert payload["required_action_count"] == 0
    assert payload["actions"] == []
    assert payload["health"]["ok"] is True


def test_fixed_cache_warmup_missing_inputs_create_actions(tmp_path: Path):
    config = FixedBacktestCacheHealthConfig(
        db_path=tmp_path / "missing.db",
        benchmark_cache_dir=tmp_path / "missing_benchmark",
        news_replay_path=tmp_path / "missing_news.jsonl",
        shared_phase1_cache_dir=tmp_path / "missing_phase1",
        shared_analyst_cache_dir=tmp_path / "missing_analyst",
    )

    plan = build_fixed_backtest_cache_warmup_plan(config)
    actions = {action.layer: action for action in plan.actions}

    assert plan.ok is False
    assert set(actions) == {"stock_price_db", "benchmark_price_cache", "news_replay_fixture"}
    assert actions["stock_price_db"].required is True
    assert "provider sync" in actions["stock_price_db"].recommended_command
    assert "Build the ^GSPC benchmark close JSONL cache" in actions["benchmark_price_cache"].recommended_command
    assert "build-news-replay-fixture" in actions["news_replay_fixture"].recommended_command


def test_fixed_cache_warmup_cli_json_and_strict_failure(tmp_path: Path, capsys):
    exit_code = main(
        [
            "cache",
            "warmup",
            "fixed-backtest",
            "--db-path",
            str(tmp_path / "missing.db"),
            "--benchmark-cache-dir",
            str(tmp_path / "missing_benchmark"),
            "--news-replay-fixture",
            str(tmp_path / "missing_news.jsonl"),
            "--json",
            "--strict",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["required_action_count"] == 3


def test_cli_parser_exposes_fixed_cache_warmup():
    args = build_parser().parse_args(["cache", "warmup", "fixed-backtest", "--json", "--strict"])

    assert args.command == "cache"
    assert args.cache_command == "warmup"
    assert args.cache_warmup_profile == "fixed-backtest"
    assert args.json is True
    assert args.strict is True


def _write_ready_cache_config(tmp_path: Path) -> FixedBacktestCacheHealthConfig:
    db_path = tmp_path / "signal_flux.db"
    _write_stock_price_db(db_path)
    benchmark_cache_dir = tmp_path / "benchmark_cache"
    benchmark_cache_dir.mkdir()
    (benchmark_cache_dir / "caret_GSPC.jsonl").write_text(
        "\n".join(
            json.dumps({"date": f"2026-06-0{day}", "close": 100.0 + day})
            for day in range(1, 6)
        )
        + "\n",
        encoding="utf-8",
    )
    news_path = tmp_path / "news_replay.jsonl"
    news_path.write_text(
        json.dumps(
            {
                "ticker": "AAPL",
                "title": "fixture",
                "publish_time": "2026-06-01T12:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return FixedBacktestCacheHealthConfig(
        db_path=db_path,
        benchmark_cache_dir=benchmark_cache_dir,
        news_replay_path=news_path,
        shared_phase1_cache_dir=tmp_path / "missing_phase1",
        shared_analyst_cache_dir=tmp_path / "missing_analyst",
    )


def _write_stock_price_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE stock_prices (
                ticker TEXT,
                date TEXT,
                open REAL,
                close REAL,
                high REAL,
                low REAL,
                volume INTEGER,
                change_pct REAL,
                PRIMARY KEY (ticker, date)
            )
            """
        )
        for ticker in ("AAPL", "MSFT", "NVDA"):
            for day in range(1, 6):
                connection.execute(
                    """
                    INSERT INTO stock_prices
                    (ticker, date, open, close, high, low, volume, change_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ticker,
                        f"2026-06-0{day}",
                        100.0,
                        101.0,
                        102.0,
                        99.0,
                        1000,
                        0.1,
                    ),
                )
        connection.commit()
    finally:
        connection.close()
