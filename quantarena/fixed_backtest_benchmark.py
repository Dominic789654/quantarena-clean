"""Run the fixed one-week QuantArena backtest benchmark."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from quantarena.backtest_visualizer import write_backtest_visualizer
from quantarena.report_artifacts import load_run_report_artifacts
from shared.utils.path_manager import get_project_root
from shared.utils.run_id import generate_run_id


BENCHMARK_MODES = ("simple", "llm", "both")
MODE_ORDER = ("simple", "llm")
DEFAULT_MARKET = "us"
DEFAULT_TICKERS = ("AAPL", "MSFT", "NVDA")
DEFAULT_START_DATE = "2026-06-01"
DEFAULT_END_DATE = "2026-06-05"
DEFAULT_CASHFLOW = 10000.0
DEFAULT_LLM_ANALYSTS = ("technical",)
DEFAULT_OUTPUT_ROOT = Path("reports/backtest/fixed_benchmarks")

REPORT_PATH_RE = re.compile(r"Reports saved to:\s*(?P<path>\S+)")
RUN_ID_RE = re.compile(r"Run ID:\s*(?P<run_id>[A-Za-z0-9_.-]+)")


RunnerExecutor = Callable[..., subprocess.CompletedProcess[str]]
VisualizerWriter = Callable[..., Any]


@dataclass(frozen=True)
class FixedBenchmarkConfig:
    """Configuration for the fixed backtest benchmark scenario."""

    market: str = DEFAULT_MARKET
    tickers: tuple[str, ...] = DEFAULT_TICKERS
    start_date: str = DEFAULT_START_DATE
    end_date: str = DEFAULT_END_DATE
    cashflow: float = DEFAULT_CASHFLOW
    llm_analysts: tuple[str, ...] = DEFAULT_LLM_ANALYSTS
    output_root: Path = DEFAULT_OUTPUT_ROOT
    run_id: str | None = None
    python_executable: str = sys.executable

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "tickers": list(self.tickers),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "cashflow": self.cashflow,
            "llm_analysts": list(self.llm_analysts),
            "output_root": str(self.output_root),
            "run_id": self.run_id,
            "python_executable": self.python_executable,
        }


@dataclass
class FixedBenchmarkRun:
    """Result for one requested benchmark mode."""

    mode: str
    ok: bool
    command: list[str]
    exit_code: int
    run_id: str | None = None
    report_dir: Path | None = None
    dashboard_path: Path | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "ok": self.ok,
            "command": list(self.command),
            "exit_code": self.exit_code,
            "run_id": self.run_id,
            "report_dir": str(self.report_dir) if self.report_dir else None,
            "dashboard_path": str(self.dashboard_path) if self.dashboard_path else None,
            "metrics": self.metrics,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
        }


@dataclass
class FixedBenchmarkResult:
    """Overall result for a fixed benchmark invocation."""

    ok: bool
    mode: str
    summary_path: Path
    config: FixedBenchmarkConfig
    runs: list[FixedBenchmarkRun]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "summary_path": str(self.summary_path),
            "config": self.config.to_dict(),
            "runs": [run.to_dict() for run in self.runs],
        }


def build_parser() -> argparse.ArgumentParser:
    """Build the fixed benchmark CLI parser."""
    parser = argparse.ArgumentParser(
        prog="run_fixed_backtest_week.py",
        description="Run QuantArena's fixed one-week backtest benchmark.",
    )
    parser.add_argument(
        "--mode",
        choices=BENCHMARK_MODES,
        default="both",
        help="Benchmark mode to run: simple, llm, or both",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory where benchmark-level summary folders are written",
    )
    parser.add_argument(
        "--run-id",
        help="Optional benchmark summary run id; defaults to a generated id",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the summary payload as JSON",
    )
    parser.add_argument(
        "--python",
        dest="python_executable",
        default=sys.executable,
        help="Python executable used to invoke run.py",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fixed benchmark from CLI arguments."""
    parser = build_parser()
    args = parser.parse_args(argv)
    config = FixedBenchmarkConfig(
        output_root=args.output_root,
        run_id=args.run_id,
        python_executable=args.python_executable,
    )
    result = run_fixed_backtest_benchmark(mode=args.mode, config=config)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        _print_human_summary(payload)
    return 0 if result.ok else 1


def run_fixed_backtest_benchmark(
    *,
    mode: str,
    config: FixedBenchmarkConfig | None = None,
    executor: RunnerExecutor | None = None,
    visualizer_writer: VisualizerWriter = write_backtest_visualizer,
) -> FixedBenchmarkResult:
    """Run the fixed benchmark and write a benchmark-level summary."""
    if mode not in BENCHMARK_MODES:
        raise ValueError(f"Unsupported benchmark mode: {mode}")

    effective_config = config or FixedBenchmarkConfig()
    benchmark_run_id = effective_config.run_id or generate_run_id("fixed_week")
    summary_dir = effective_config.output_root / benchmark_run_id
    summary_path = summary_dir / "summary.json"
    summary_dir.mkdir(parents=True, exist_ok=True)

    project_root = get_project_root()
    run_executor = executor or subprocess.run
    runs = [
        _run_mode(
            mode=current_mode,
            config=effective_config,
            project_root=project_root,
            executor=run_executor,
            visualizer_writer=visualizer_writer,
        )
        for current_mode in _expand_modes(mode)
    ]
    result = FixedBenchmarkResult(
        ok=all(run.ok for run in runs),
        mode=mode,
        summary_path=summary_path,
        config=FixedBenchmarkConfig(
            market=effective_config.market,
            tickers=effective_config.tickers,
            start_date=effective_config.start_date,
            end_date=effective_config.end_date,
            cashflow=effective_config.cashflow,
            llm_analysts=effective_config.llm_analysts,
            output_root=effective_config.output_root,
            run_id=benchmark_run_id,
            python_executable=effective_config.python_executable,
        ),
        runs=runs,
    )
    summary_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return result


def build_backtest_command(
    mode: str,
    config: FixedBenchmarkConfig | None = None,
    *,
    project_root: Path | None = None,
) -> list[str]:
    """Build the `run.py` command for one fixed benchmark mode."""
    if mode not in MODE_ORDER:
        raise ValueError(f"Unsupported executable benchmark mode: {mode}")

    effective_config = config or FixedBenchmarkConfig()
    root = project_root or get_project_root()
    command = [
        effective_config.python_executable,
        str(root / "run.py"),
        "--no-banner",
        "--mode",
        "backtest",
        "--market",
        effective_config.market,
        "--tickers",
        ",".join(effective_config.tickers),
        "--start-date",
        effective_config.start_date,
        "--end-date",
        effective_config.end_date,
        "--cashflow",
        _format_float_arg(effective_config.cashflow),
    ]
    if mode == "llm":
        command.extend(["--use-llm", "--analysts", ",".join(effective_config.llm_analysts)])
    return command


def _run_mode(
    *,
    mode: str,
    config: FixedBenchmarkConfig,
    project_root: Path,
    executor: RunnerExecutor,
    visualizer_writer: VisualizerWriter,
) -> FixedBenchmarkRun:
    command = build_backtest_command(mode, config, project_root=project_root)
    completed = executor(
        command,
        cwd=str(project_root),
        text=True,
        capture_output=True,
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    report_dir = _discover_report_dir(stdout=stdout, stderr=stderr, project_root=project_root)
    run_id = _discover_run_id(stdout=stdout, stderr=stderr, report_dir=report_dir)

    if completed.returncode != 0:
        return FixedBenchmarkRun(
            mode=mode,
            ok=False,
            command=command,
            exit_code=completed.returncode,
            run_id=run_id,
            report_dir=report_dir,
            stdout=stdout,
            stderr=stderr,
            error=_last_error_text(stdout=stdout, stderr=stderr) or "backtest command failed",
        )

    if report_dir is None:
        return FixedBenchmarkRun(
            mode=mode,
            ok=False,
            command=command,
            exit_code=completed.returncode,
            run_id=run_id,
            stdout=stdout,
            stderr=stderr,
            error="could not discover report directory from backtest output",
        )

    dashboard_path = report_dir / "dashboard.html"
    dashboard_result = visualizer_writer(
        root=report_dir,
        output=dashboard_path,
        title=f"Fixed Week {mode.upper()} Benchmark",
    )
    dashboard_ok = bool(getattr(dashboard_result, "ok", dashboard_path.exists()))
    dashboard_error = None
    if not dashboard_ok:
        errors = getattr(dashboard_result, "errors", ())
        dashboard_error = f"dashboard generation failed: {errors}"

    artifacts = load_run_report_artifacts(report_dir)
    return FixedBenchmarkRun(
        mode=mode,
        ok=dashboard_ok and artifacts.ok,
        command=command,
        exit_code=completed.returncode,
        run_id=run_id or artifacts.run_id,
        report_dir=report_dir,
        dashboard_path=dashboard_path if dashboard_ok else None,
        metrics=dict(artifacts.metrics),
        stdout=stdout,
        stderr=stderr,
        error=dashboard_error or _artifact_error_text(artifacts.errors),
    )


def _expand_modes(mode: str) -> tuple[str, ...]:
    if mode == "both":
        return MODE_ORDER
    if mode in MODE_ORDER:
        return (mode,)
    raise ValueError(f"Unsupported benchmark mode: {mode}")


def _discover_report_dir(*, stdout: str, stderr: str, project_root: Path) -> Path | None:
    combined = "\n".join([stdout, stderr])
    matches = list(REPORT_PATH_RE.finditer(combined))
    if matches:
        raw_path = matches[-1].group("path").rstrip("/")
        path = Path(raw_path)
        return path if path.is_absolute() else project_root / path

    run_id = _discover_run_id(stdout=stdout, stderr=stderr, report_dir=None)
    if run_id:
        fallback = project_root / "reports" / "backtest" / run_id
        if fallback.exists():
            return fallback
    return None


def _discover_run_id(*, stdout: str, stderr: str, report_dir: Path | None) -> str | None:
    if report_dir is not None:
        return report_dir.name
    combined = "\n".join([stdout, stderr])
    matches = list(RUN_ID_RE.finditer(combined))
    return matches[-1].group("run_id") if matches else None


def _artifact_error_text(errors: Iterable[Any]) -> str | None:
    messages = [
        f"{getattr(error, 'path', '<unknown>')}: {getattr(error, 'message', error)}"
        for error in errors
    ]
    return "; ".join(messages) if messages else None


def _last_error_text(*, stdout: str, stderr: str) -> str | None:
    lines = [line.strip() for line in "\n".join([stderr, stdout]).splitlines() if line.strip()]
    for line in reversed(lines):
        if line.upper().startswith("ERROR") or "Traceback" in line:
            return line
    return lines[-1] if lines else None


def _format_float_arg(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _print_human_summary(payload: Mapping[str, Any]) -> None:
    print("Fixed backtest benchmark")
    print(f"mode: {payload['mode']}")
    print(f"ok: {payload['ok']}")
    print(f"summary: {payload['summary_path']}")
    for run in payload["runs"]:
        status = "ok" if run["ok"] else "failed"
        print(f"- {run['mode']}: {status}")
        if run.get("run_id"):
            print(f"  run_id: {run['run_id']}")
        if run.get("report_dir"):
            print(f"  report_dir: {run['report_dir']}")
        if run.get("dashboard_path"):
            print(f"  dashboard: {run['dashboard_path']}")
        if run.get("error"):
            print(f"  error: {run['error']}")


if __name__ == "__main__":
    raise SystemExit(main())
