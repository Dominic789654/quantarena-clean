"""Tests for cache health reporting."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from quantarena.cache_health import (
    FixedBacktestCacheHealthConfig,
    run_fixed_backtest_cache_health,
)
from quantarena.cli import build_parser, main


def test_fixed_cache_health_reports_ready_layers(tmp_path: Path):
    config = _write_ready_cache_config(tmp_path)

    report = run_fixed_backtest_cache_health(config)
    payload = report.to_dict()

    assert report.ok is True
    assert payload["profile"] == "fixed-backtest"
    assert payload["findings"] == []
    layers = {layer["name"]: layer for layer in payload["layers"]}
    assert layers["stock_price_db"]["status"] == "hit"
    assert layers["stock_price_db"]["details"]["tickers"]["AAPL"]["rows"] == 5
    assert layers["benchmark_price_cache"]["status"] == "hit"
    assert layers["news_replay_fixture"]["status"] == "hit"
    assert layers["shared_phase1_cache"]["status"] == "missing_optional"


def test_fixed_cache_health_reports_missing_required_layers(tmp_path: Path):
    config = _write_ready_cache_config(tmp_path)
    config = FixedBacktestCacheHealthConfig(
        db_path=tmp_path / "missing.db",
        benchmark_cache_dir=config.benchmark_cache_dir,
        news_replay_path=tmp_path / "missing_news.jsonl",
        shared_phase1_cache_dir=config.shared_phase1_cache_dir,
        shared_analyst_cache_dir=config.shared_analyst_cache_dir,
    )

    report = run_fixed_backtest_cache_health(config)

    assert report.ok is False
    assert {finding.layer for finding in report.findings} == {
        "stock_price_db",
        "news_replay_fixture",
    }


def test_cache_health_cli_json_and_strict_failure(tmp_path: Path, capsys):
    exit_code = main(
        [
            "cache",
            "health",
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
    assert payload["profile"] == "fixed-backtest"


def test_cache_health_cli_parser_exposes_health_command():
    args = build_parser().parse_args(["cache", "health", "--json", "--strict"])

    assert args.command == "cache"
    assert args.cache_command == "health"
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


def test_stock_price_layer_reads_wal_db_on_readonly_dir(tmp_path):
    """A WAL-mode signal_flux.db on a read-only mount must still report hits.

    WAL readers need write access to the -shm sidecar even under mode=ro;
    the immutable=1 fallback keeps prebaked read-only caches readable."""
    import os
    import sqlite3 as _sqlite3

    if os.geteuid() == 0:
        pytest.skip("directory write-permission bits do not bind for root")

    db_path = tmp_path / "signal_flux.db"
    conn = _sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        "CREATE TABLE stock_prices (ticker TEXT, date TEXT, close REAL)"
    )
    conn.execute(
        "INSERT INTO stock_prices VALUES ('AAA', '2026-01-05', 10.0)"
    )
    conn.commit()
    # Checkpoint so the row lives in the main file, then drop sidecars the
    # way a prebaked-artifact copy would.
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    os.chmod(tmp_path, 0o555)
    try:
        from quantarena.cache_health import _open_readonly_connection, _stock_price_dates

        connection = _open_readonly_connection(str(db_path))
        try:
            dates = _stock_price_dates(connection, "AAA", "2026-01-01", "2026-01-31")
        finally:
            connection.close()
        assert dates == {"2026-01-05"}
    finally:
        os.chmod(tmp_path, 0o755)


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
