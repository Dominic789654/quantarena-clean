"""Tests for backtest HTML visualizer generation."""

from __future__ import annotations

import json
from pathlib import Path

from quantarena.backtest_visualizer import write_backtest_visualizer
from quantarena.cli import build_parser, main


def test_write_backtest_visualizer_embeds_payload_and_ticker_controls(tmp_path: Path):
    report_root = tmp_path / "run"
    _write_report(report_root)
    output = tmp_path / "visualizer.html"

    result = write_backtest_visualizer(report_root, output=output, title="Fixed Week Dashboard")

    assert result.ok is True
    assert result.run_id == "fixed_week"
    assert result.tickers == ("AAPL", "MSFT")
    assert output.is_file()
    page = output.read_text(encoding="utf-8")
    assert '<option value="AAPL">AAPL</option>' in page
    assert '<option value="MSFT">MSFT</option>' in page
    assert '<div class="label">Final Value</div>' in page
    assert '<table><thead><tr><th>Date</th><th>Ticker</th>' in page
    assert '<polyline fill="none" stroke="#2563eb"' in page
    assert "Fixed Week Dashboard" in page
    assert "id=\"backtest-data\"" in page
    assert "id=\"ticker-filter\"" in page
    assert "id=\"chart-tooltip\"" in page
    assert "showChartTooltip" in page
    assert "mousemove" in page
    assert "Portfolio:" in page
    assert "chart-hover-target" in page
    assert "<title>2026-06-01" in page
    assert "Daily return:" in page
    assert "All tickers" in page
    assert "renderFilteredTables" in page
    assert "Equity Curve" in page
    assert '"tickers": ["AAPL", "MSFT"]' in page


def test_write_backtest_visualizer_reports_errors_without_partial_html(tmp_path: Path):
    report_root = tmp_path / "missing"
    report_root.mkdir()
    (report_root / "metrics.json").write_text(
        json.dumps({"run_id": "bad", "tickers": ["AAPL"], "metrics": {"total_return": 1.0}}),
        encoding="utf-8",
    )
    (report_root / "equity_curve.csv").write_text(
        "date,total_value,daily_return,cashflow\n2026-01-01,100.0,0.0,100.0\n",
        encoding="utf-8",
    )
    output = tmp_path / "missing.html"

    result = write_backtest_visualizer(report_root, output=output)

    assert result.ok is False
    assert output.exists() is False
    assert result.errors
    assert any(error["path"].endswith("trades.csv") for error in result.errors)


def test_cli_parser_exposes_report_visualize_subcommand(tmp_path: Path):
    parser = build_parser()
    args = parser.parse_args(
        [
            "report",
            "visualize",
            "--root",
            str(tmp_path),
            "--output",
            str(tmp_path / "out.html"),
            "--json",
        ]
    )

    assert args.command == "report"
    assert args.report_command == "visualize"
    assert args.root == tmp_path
    assert args.output == tmp_path / "out.html"
    assert args.json is True


def test_report_visualize_command_outputs_json(tmp_path: Path, capsys):
    report_root = tmp_path / "run"
    _write_report(report_root)
    output = tmp_path / "dashboard.html"

    exit_code = main(
        [
            "report",
            "visualize",
            "--root",
            str(report_root),
            "--output",
            str(output),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["output"] == str(output)
    assert payload["run_id"] == "fixed_week"
    assert payload["tickers"] == ["AAPL", "MSFT"]
    assert output.is_file()


def _write_report(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "metrics.json").write_text(
        json.dumps(
            {
                "run_id": "fixed_week",
                "start_date": "2026-06-01",
                "end_date": "2026-06-05",
                "market": "us",
                "tickers": ["AAPL", "MSFT"],
                "initial_cash": 10000.0,
                "metrics": {
                    "total_return": 1.25,
                    "max_drawdown": 0.4,
                    "sharpe_ratio": 1.7,
                    "avg_cash_ratio": 0.5,
                    "avg_gross_exposure": 0.5,
                    "total_trades": 2,
                },
                "summary": {
                    "final_value": 10125.0,
                    "total_return": 1.25,
                    "total_trades": 2,
                    "final_positions": {
                        "AAPL": {"shares": 3, "value": 900.0, "last_price": 300.0},
                        "MSFT": {"shares": 1, "value": 420.0, "last_price": 420.0},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "equity_curve.csv").write_text(
        "date,total_value,daily_return,cashflow,benchmark_value,benchmark_return\n"
        "2026-06-01,10000.0,0.0,10000.0,10000.0,0.0\n"
        "2026-06-02,10125.0,1.25,8680.0,10080.0,0.8\n",
        encoding="utf-8",
    )
    (root / "trades.csv").write_text(
        "date,ticker,action,shares,price,value,justification\n"
        "2026-06-01,AAPL,BUY,3,300.0,900.0,entry\n"
        "2026-06-02,MSFT,BUY,1,420.0,420.0,entry\n",
        encoding="utf-8",
    )
