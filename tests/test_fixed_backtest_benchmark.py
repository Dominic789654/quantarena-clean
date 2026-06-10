"""Tests for the fixed backtest benchmark runner."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from quantarena.fixed_backtest_benchmark import (
    FixedBenchmarkConfig,
    build_backtest_command,
    run_fixed_backtest_benchmark,
)


def test_build_backtest_command_uses_fixed_simple_defaults(tmp_path: Path):
    config = FixedBenchmarkConfig(output_root=tmp_path, python_executable="python")

    command = build_backtest_command("simple", config, project_root=tmp_path)

    assert command == [
        "python",
        str(tmp_path / "run.py"),
        "--no-banner",
        "--mode",
        "backtest",
        "--market",
        "us",
        "--tickers",
        "AAPL,MSFT,NVDA",
        "--start-date",
        "2026-06-01",
        "--end-date",
        "2026-06-05",
        "--cashflow",
        "10000",
    ]


def test_build_backtest_command_adds_llm_technical_analyst(tmp_path: Path):
    config = FixedBenchmarkConfig(output_root=tmp_path, python_executable="python")

    command = build_backtest_command("llm", config, project_root=tmp_path)

    assert command[-3:] == ["--use-llm", "--analysts", "technical"]


def test_run_fixed_benchmark_both_writes_summary_and_dashboards(tmp_path: Path):
    reports_root = tmp_path / "reports" / "backtest"
    calls: list[list[str]] = []
    visualized: list[tuple[Path, Path, str]] = []

    def fake_executor(command, cwd, text, capture_output):
        del cwd, text, capture_output
        calls.append(list(command))
        mode = "llm" if "--use-llm" in command else "simple"
        run_id = f"{mode}_run"
        _write_report(
            reports_root / run_id,
            run_id=run_id,
            total_return=1.2 if mode == "simple" else -0.4,
            benchmark_source="index:^GSPC" if mode == "simple" else "equal_weight_basket",
            benchmark_diagnostics=mode == "simple",
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=f"Run ID: {run_id}\nReports saved to: {reports_root / run_id}/\n",
            stderr="",
        )

    def fake_visualizer_writer(root, output, title):
        visualized.append((Path(root), Path(output), title))
        Path(output).write_text("<html>dashboard</html>", encoding="utf-8")
        return SimpleNamespace(ok=True, errors=())

    config = FixedBenchmarkConfig(
        output_root=tmp_path / "benchmarks",
        run_id="fixed_summary",
        python_executable="python",
    )

    result = run_fixed_backtest_benchmark(
        mode="both",
        config=config,
        executor=fake_executor,
        visualizer_writer=fake_visualizer_writer,
    )

    payload = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert result.ok is True
    assert result.summary_path == tmp_path / "benchmarks" / "fixed_summary" / "summary.json"
    assert [run["mode"] for run in payload["runs"]] == ["simple", "llm"]
    assert [run.mode for run in result.runs] == ["simple", "llm"]
    assert len(calls) == 2
    assert "--use-llm" not in calls[0]
    assert "--use-llm" in calls[1]
    assert [item[0].name for item in visualized] == ["simple_run", "llm_run"]
    assert all(item[1].name == "dashboard.html" for item in visualized)
    assert payload["config"]["tickers"] == ["AAPL", "MSFT", "NVDA"]
    assert payload["runs"][0]["metrics"]["total_return"] == 1.2
    assert payload["runs"][1]["dashboard_path"].endswith("dashboard.html")
    assert payload["runs"][0]["benchmark_source"] == "index:^GSPC"
    assert payload["runs"][0]["benchmark_diagnostics_path"].endswith("benchmark_diagnostics.jsonl")
    assert payload["runs"][1]["benchmark_source"] == "equal_weight_basket"
    assert payload["runs"][1]["benchmark_diagnostics_path"] is None


def test_run_fixed_benchmark_keeps_success_when_later_mode_fails(tmp_path: Path):
    reports_root = tmp_path / "reports" / "backtest"

    def fake_executor(command, cwd, text, capture_output):
        del cwd, text, capture_output
        if "--use-llm" in command:
            return subprocess.CompletedProcess(
                args=command,
                returncode=2,
                stdout="Run ID: llm_failed\n",
                stderr="ERROR: missing LLM key\n",
            )
        _write_report(reports_root / "simple_run", run_id="simple_run")
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=f"Run ID: simple_run\nReports saved to: {reports_root / 'simple_run'}/\n",
            stderr="",
        )

    def fake_visualizer_writer(root, output, title):
        del root, title
        Path(output).write_text("<html>dashboard</html>", encoding="utf-8")
        return SimpleNamespace(ok=True, errors=())

    result = run_fixed_backtest_benchmark(
        mode="both",
        config=FixedBenchmarkConfig(output_root=tmp_path / "benchmarks", run_id="summary"),
        executor=fake_executor,
        visualizer_writer=fake_visualizer_writer,
    )

    payload = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert result.ok is False
    assert payload["ok"] is False
    assert payload["runs"][0]["ok"] is True
    assert payload["runs"][1]["ok"] is False
    assert payload["runs"][1]["exit_code"] == 2
    assert payload["runs"][1]["run_id"] == "llm_failed"
    assert "missing LLM key" in payload["runs"][1]["error"]


def test_run_fixed_benchmark_reports_missing_report_directory(tmp_path: Path):
    def fake_executor(command, cwd, text, capture_output):
        del cwd, text, capture_output
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="Run ID: lost\n", stderr="")

    result = run_fixed_backtest_benchmark(
        mode="simple",
        config=FixedBenchmarkConfig(output_root=tmp_path, run_id="summary"),
        executor=fake_executor,
    )

    assert result.ok is False
    assert result.runs[0].run_id == "lost"
    assert result.runs[0].report_dir is None
    assert "could not discover report directory" in (result.runs[0].error or "")


def _write_report(
    root: Path,
    *,
    run_id: str,
    total_return: float = 1.0,
    benchmark_source: str | None = None,
    benchmark_diagnostics: bool = False,
) -> None:
    root.mkdir(parents=True)
    (root / "metrics.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "start_date": "2026-06-01",
                "end_date": "2026-06-05",
                "market": "us",
                "tickers": ["AAPL", "MSFT", "NVDA"],
                "initial_cash": 10000.0,
                "metrics": {
                    "total_return": total_return,
                    "max_drawdown": 0.1,
                    "sharpe_ratio": 1.0,
                    "total_trades": 1,
                    "benchmark_source": benchmark_source,
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "equity_curve.csv").write_text(
        "date,total_value,daily_return,cashflow\n2026-06-01,10000,0,10000\n",
        encoding="utf-8",
    )
    (root / "trades.csv").write_text(
        "date,ticker,action,shares,price,value\n2026-06-01,AAPL,BUY,1,300,300\n",
        encoding="utf-8",
    )
    if benchmark_diagnostics:
        (root / "benchmark_diagnostics.jsonl").write_text(
            json.dumps(
                {
                    "index_code": "^GSPC",
                    "provider": "cache",
                    "status": "hit",
                }
            )
            + "\n",
            encoding="utf-8",
        )
