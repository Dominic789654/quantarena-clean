"""Regression gate for fixed QuantArena backtest benchmark summaries."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from quantarena.fixed_backtest_benchmark import (
    BENCHMARK_MODES,
    DEFAULT_MULTI_ANALYSTS,
    DEFAULT_MULTI_MAX_WORKERS,
    DEFAULT_MULTI_PERSONALITIES,
    DEFAULT_OUTPUT_ROOT,
    FixedBenchmarkConfig,
    run_fixed_backtest_benchmark,
)


DEFAULT_BASELINE_PATH = Path(
    "tests/fixtures/fixed_backtest_data/fixed_backtest_regression_baseline.json"
)


@dataclass(frozen=True)
class FixedBacktestGateFinding:
    """One failed fixed benchmark regression check."""

    check: str
    message: str
    mode: str | None = None
    path: str | None = None
    actual: Any = None
    expected: Any = None
    tolerance: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "message": self.message,
            "mode": self.mode,
            "path": self.path,
            "actual": self.actual,
            "expected": self.expected,
            "tolerance": self.tolerance,
        }


@dataclass(frozen=True)
class FixedBacktestGateResult:
    """Regression gate result for a fixed benchmark summary."""

    ok: bool
    summary_path: Path
    baseline_path: Path
    profile: str
    findings: tuple[FixedBacktestGateFinding, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary_path": str(self.summary_path),
            "baseline_path": str(self.baseline_path),
            "profile": self.profile,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def build_parser() -> argparse.ArgumentParser:
    """Build the fixed regression gate CLI parser."""
    parser = argparse.ArgumentParser(
        prog="run_fixed_backtest_regression_gate.py",
        description="Evaluate fixed backtest benchmark summaries against a baseline.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        help="Existing fixed benchmark summary JSON to evaluate",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help="Baseline JSON with fixed benchmark regression expectations",
    )
    parser.add_argument(
        "--profile",
        help="Baseline profile to use; defaults to the summary or requested mode",
    )
    parser.add_argument(
        "--mode",
        choices=BENCHMARK_MODES,
        help="Run the fixed benchmark mode before evaluating the generated summary",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory where benchmark-level summary folders are written when running",
    )
    parser.add_argument(
        "--run-id",
        help="Optional benchmark summary run id when running the fixed benchmark first",
    )
    parser.add_argument(
        "--news-replay-fixture",
        type=Path,
        help="Optional JSON/JSONL company-news replay fixture passed to child backtests",
    )
    parser.add_argument(
        "--benchmark-cache-dir",
        type=Path,
        help="Optional benchmark close-price cache directory passed to child backtests",
    )
    parser.add_argument(
        "--multi-analysts",
        default=",".join(DEFAULT_MULTI_ANALYSTS),
        help="Comma-separated analysts for fixed multi-personality mode",
    )
    parser.add_argument(
        "--multi-personalities",
        default=",".join(DEFAULT_MULTI_PERSONALITIES),
        help="Comma-separated personalities for fixed multi-personality mode",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MULTI_MAX_WORKERS,
        help="Maximum workers for fixed multi-personality mode",
    )
    parser.add_argument(
        "--python",
        dest="python_executable",
        default=sys.executable,
        help="Python executable used to invoke run.py when running first",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the gate result as JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fixed benchmark regression gate from CLI arguments."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.summary and args.mode:
        parser.error("--summary and --mode are mutually exclusive")
    if not args.summary and not args.mode:
        parser.error("one of --summary or --mode is required")

    summary_path = args.summary
    profile = args.profile
    if summary_path is None:
        config = FixedBenchmarkConfig(
            output_root=args.output_root,
            run_id=args.run_id,
            python_executable=args.python_executable,
            multi_analysts=_parse_csv_tuple(args.multi_analysts),
            multi_personalities=_parse_csv_tuple(args.multi_personalities),
            multi_max_workers=args.max_workers,
            news_replay_path=args.news_replay_fixture,
            benchmark_cache_dir=args.benchmark_cache_dir,
        )
        benchmark_result = run_fixed_backtest_benchmark(mode=str(args.mode), config=config)
        summary_path = benchmark_result.summary_path
        profile = profile or str(args.mode)

    result = evaluate_fixed_backtest_summary(
        summary_path=summary_path,
        baseline_path=args.baseline,
        profile=profile,
    )
    if args.json:
        print(json.dumps(result.to_dict(), sort_keys=True))
    else:
        _print_human_result(result)
    return 0 if result.ok else 1


def evaluate_fixed_backtest_summary(
    *,
    summary_path: Path,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    profile: str | None = None,
) -> FixedBacktestGateResult:
    """Evaluate a fixed benchmark summary against a baseline profile."""
    summary = _read_json(summary_path)
    baseline_doc = _read_json(baseline_path)
    profile_name, baseline = _select_baseline_profile(
        baseline_doc=baseline_doc,
        requested_profile=profile,
        summary=summary,
    )

    findings: list[FixedBacktestGateFinding] = []
    runs_by_mode = _runs_by_mode(summary)
    mode_expectations = _mapping(baseline.get("modes"))
    required_modes = baseline.get("required_modes") or list(mode_expectations)
    for mode in required_modes:
        mode_name = str(mode)
        run = runs_by_mode.get(mode_name)
        if run is None:
            findings.append(
                FixedBacktestGateFinding(
                    check="required_mode",
                    mode=mode_name,
                    message=f"required mode {mode_name!r} is missing from summary",
                    expected=mode_name,
                )
            )
            continue
        _evaluate_mode(
            mode=mode_name,
            run=run,
            expectation=_mapping(mode_expectations.get(mode_name)),
            summary_path=summary_path,
            findings=findings,
        )

    return FixedBacktestGateResult(
        ok=not findings,
        summary_path=summary_path,
        baseline_path=baseline_path,
        profile=profile_name,
        findings=tuple(findings),
    )


def _evaluate_mode(
    *,
    mode: str,
    run: Mapping[str, Any],
    expectation: Mapping[str, Any],
    summary_path: Path,
    findings: list[FixedBacktestGateFinding],
) -> None:
    if "ok" in expectation and bool(run.get("ok")) is not bool(expectation["ok"]):
        findings.append(
            FixedBacktestGateFinding(
                check="mode_ok",
                mode=mode,
                message=f"mode {mode!r} ok status changed",
                actual=bool(run.get("ok")),
                expected=bool(expectation["ok"]),
            )
        )

    expected_source = expectation.get("benchmark_source")
    if expected_source is not None and run.get("benchmark_source") != expected_source:
        findings.append(
            FixedBacktestGateFinding(
                check="benchmark_source",
                mode=mode,
                message=f"mode {mode!r} benchmark source changed",
                actual=run.get("benchmark_source"),
                expected=expected_source,
            )
        )

    for field_name in expectation.get("required_paths", []):
        _check_required_path(
            mode=mode,
            run=run,
            field_name=str(field_name),
            summary_path=summary_path,
            findings=findings,
        )

    if expectation.get("artifact_review_ok"):
        review = run.get("artifact_review")
        if not isinstance(review, Mapping) or review.get("ok") is not True:
            findings.append(
                FixedBacktestGateFinding(
                    check="artifact_review_ok",
                    mode=mode,
                    message=f"mode {mode!r} artifact review is missing or not ok",
                    actual=review.get("ok") if isinstance(review, Mapping) else None,
                    expected=True,
                )
            )

    _evaluate_metric_expectations(
        mode=mode,
        run=run,
        expectations=_mapping(expectation.get("metrics")),
        findings=findings,
    )
    _evaluate_personality_expectations(
        mode=mode,
        run=run,
        expectation=expectation,
        findings=findings,
    )
    _evaluate_news_diagnostics(
        mode=mode,
        run=run,
        expectation=_mapping(expectation.get("news_diagnostics")),
        summary_path=summary_path,
        findings=findings,
    )
    _evaluate_benchmark_diagnostics(
        mode=mode,
        run=run,
        expectation=_mapping(expectation.get("benchmark_diagnostics")),
        summary_path=summary_path,
        findings=findings,
    )


def _evaluate_metric_expectations(
    *,
    mode: str,
    run: Mapping[str, Any],
    expectations: Mapping[str, Any],
    findings: list[FixedBacktestGateFinding],
) -> None:
    for metric_path, raw_expectation in expectations.items():
        expectation = _mapping(raw_expectation)
        expected = expectation.get("expected")
        tolerance = _float_or_none(expectation.get("abs_tolerance")) or 0.0
        actual = _get_path(run, str(metric_path))
        _check_numeric_value(
            mode=mode,
            check="metric",
            path=str(metric_path),
            actual=actual,
            expected=expected,
            tolerance=tolerance,
            findings=findings,
        )


def _evaluate_personality_expectations(
    *,
    mode: str,
    run: Mapping[str, Any],
    expectation: Mapping[str, Any],
    findings: list[FixedBacktestGateFinding],
) -> None:
    required_personalities = [str(item) for item in expectation.get("required_personalities", [])]
    personality_rows = _personality_rows(run)
    for personality in required_personalities:
        if personality not in personality_rows:
            findings.append(
                FixedBacktestGateFinding(
                    check="required_personality",
                    mode=mode,
                    path="metrics.personality_summary",
                    message=f"mode {mode!r} is missing personality {personality!r}",
                    expected=personality,
                )
            )

    metric_expectations = _mapping(expectation.get("personality_metrics"))
    for personality_key, raw_fields in metric_expectations.items():
        fields = _mapping(raw_fields)
        personalities = required_personalities if str(personality_key) == "*" else [str(personality_key)]
        for personality in personalities:
            row = personality_rows.get(personality)
            if row is None:
                continue
            for field_name, raw_metric_expectation in fields.items():
                metric_expectation = _mapping(raw_metric_expectation)
                expected = metric_expectation.get("expected")
                tolerance = _float_or_none(metric_expectation.get("abs_tolerance")) or 0.0
                actual = row.get(str(field_name))
                _check_numeric_value(
                    mode=mode,
                    check="personality_metric",
                    path=f"metrics.personality_summary[{personality!r}].{field_name}",
                    actual=actual,
                    expected=expected,
                    tolerance=tolerance,
                    findings=findings,
                )


def _evaluate_news_diagnostics(
    *,
    mode: str,
    run: Mapping[str, Any],
    expectation: Mapping[str, Any],
    summary_path: Path,
    findings: list[FixedBacktestGateFinding],
) -> None:
    if not expectation.get("require_nonzero_final_count"):
        return
    records = _read_jsonl_artifact_records(
        raw_paths=_diagnostic_paths(run, "news_diagnostics"),
        summary_path=summary_path,
        mode=mode,
        check="news_diagnostics",
        findings=findings,
    )
    if records and any(_final_news_count(record) > 0 for record in records):
        return
    findings.append(
        FixedBacktestGateFinding(
            check="news_diagnostics_nonzero",
            mode=mode,
            message=f"mode {mode!r} has no news diagnostics rows with positive final_count",
            actual=0,
            expected="positive final_count",
        )
    )


def _evaluate_benchmark_diagnostics(
    *,
    mode: str,
    run: Mapping[str, Any],
    expectation: Mapping[str, Any],
    summary_path: Path,
    findings: list[FixedBacktestGateFinding],
) -> None:
    cache_hits = expectation.get("cache_hits")
    if not isinstance(cache_hits, list) or not cache_hits:
        return
    records = _read_jsonl_artifact_records(
        raw_paths=_diagnostic_paths(run, "benchmark_diagnostics"),
        summary_path=summary_path,
        mode=mode,
        check="benchmark_diagnostics",
        findings=findings,
    )
    for raw_cache_hit in cache_hits:
        cache_hit = _mapping(raw_cache_hit)
        expected_index = str(cache_hit.get("index_code", ""))
        matched = any(
            str(record.get("index_code")) == expected_index
            and str(record.get("provider")) == "cache"
            and str(record.get("status")) == "hit"
            for record in records
        )
        if not matched:
            findings.append(
                FixedBacktestGateFinding(
                    check="benchmark_cache_hit",
                    mode=mode,
                    message=(
                        f"mode {mode!r} has no benchmark diagnostics cache hit "
                        f"for index {expected_index!r}"
                    ),
                    actual=None,
                    expected={"index_code": expected_index, "provider": "cache", "status": "hit"},
                )
            )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"JSON file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload


def _select_baseline_profile(
    *,
    baseline_doc: Mapping[str, Any],
    requested_profile: str | None,
    summary: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any]]:
    profiles = _mapping(baseline_doc.get("profiles"))
    profile_name = requested_profile or str(summary.get("mode") or "")
    if profile_name in profiles:
        return profile_name, _mapping(profiles[profile_name])
    if requested_profile:
        raise ValueError(f"baseline profile {requested_profile!r} was not found")
    if len(profiles) == 1:
        only_profile = next(iter(profiles))
        return str(only_profile), _mapping(profiles[only_profile])
    raise ValueError("could not infer baseline profile; pass --profile")


def _runs_by_mode(summary: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    runs = summary.get("runs")
    if not isinstance(runs, list):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        mode = run.get("mode")
        if mode:
            result[str(mode)] = run
    return result


def _check_required_path(
    *,
    mode: str,
    run: Mapping[str, Any],
    field_name: str,
    summary_path: Path,
    findings: list[FixedBacktestGateFinding],
) -> None:
    raw_path = run.get(field_name)
    if not raw_path:
        findings.append(
            FixedBacktestGateFinding(
                check="required_path",
                mode=mode,
                path=field_name,
                message=f"mode {mode!r} is missing required path field {field_name!r}",
                expected="existing path",
            )
        )
        return
    resolved_path = _resolve_artifact_path(raw_path=raw_path, summary_path=summary_path)
    if not resolved_path.exists():
        findings.append(
            FixedBacktestGateFinding(
                check="required_path",
                mode=mode,
                path=field_name,
                message=f"mode {mode!r} required path does not exist",
                actual=str(resolved_path),
                expected="existing path",
            )
        )


def _check_numeric_value(
    *,
    mode: str,
    check: str,
    path: str,
    actual: Any,
    expected: Any,
    tolerance: float,
    findings: list[FixedBacktestGateFinding],
) -> None:
    actual_number = _float_or_none(actual)
    expected_number = _float_or_none(expected)
    if actual_number is None or expected_number is None:
        findings.append(
            FixedBacktestGateFinding(
                check=check,
                mode=mode,
                path=path,
                message=f"mode {mode!r} numeric check {path!r} is not comparable",
                actual=actual,
                expected=expected,
                tolerance=tolerance,
            )
        )
        return
    if abs(actual_number - expected_number) > tolerance:
        findings.append(
            FixedBacktestGateFinding(
                check=check,
                mode=mode,
                path=path,
                message=f"mode {mode!r} numeric check {path!r} exceeded tolerance",
                actual=actual_number,
                expected=expected_number,
                tolerance=tolerance,
            )
        )


def _personality_rows(run: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    metrics = run.get("metrics")
    if not isinstance(metrics, Mapping):
        return {}
    rows = metrics.get("personality_summary")
    if not isinstance(rows, list):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        personality = row.get("Personality") or row.get("personality")
        if personality:
            result[str(personality)] = row
    return result


def _diagnostic_paths(run: Mapping[str, Any], artifact_prefix: str) -> list[Any]:
    paths = run.get(f"{artifact_prefix}_paths")
    if isinstance(paths, list):
        return paths
    single_path = run.get(f"{artifact_prefix}_path")
    return [single_path] if single_path else []


def _read_jsonl_artifact_records(
    *,
    raw_paths: Sequence[Any],
    summary_path: Path,
    mode: str,
    check: str,
    findings: list[FixedBacktestGateFinding],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not raw_paths:
        findings.append(
            FixedBacktestGateFinding(
                check=check,
                mode=mode,
                message=f"mode {mode!r} has no referenced {check} files",
                expected="at least one JSONL diagnostics file",
            )
        )
        return records

    for raw_path in raw_paths:
        path = _resolve_artifact_path(raw_path=raw_path, summary_path=summary_path)
        if not path.is_file():
            findings.append(
                FixedBacktestGateFinding(
                    check=check,
                    mode=mode,
                    path=str(raw_path),
                    message=f"mode {mode!r} diagnostics file does not exist",
                    actual=str(path),
                    expected="existing JSONL diagnostics file",
                )
            )
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                findings.append(
                    FixedBacktestGateFinding(
                        check=check,
                        mode=mode,
                        path=f"{path}:{line_number}",
                        message=f"mode {mode!r} diagnostics row is invalid JSON: {exc}",
                    )
                )
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _resolve_artifact_path(*, raw_path: Any, summary_path: Path) -> Path:
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    summary_relative = summary_path.parent / path
    if summary_relative.exists():
        return summary_relative
    return path


def _final_news_count(record: Mapping[str, Any]) -> int:
    count = _float_or_none(record.get("final_count"))
    if count is None:
        count = _float_or_none(record.get("final_article_count"))
    return int(count or 0)


def _get_path(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        return None
    return current


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_csv_tuple(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return ()
    return tuple(item.strip() for item in raw_value.split(",") if item.strip())


def _print_human_result(result: FixedBacktestGateResult) -> None:
    print("Fixed backtest regression gate")
    print(f"summary: {result.summary_path}")
    print(f"baseline: {result.baseline_path}")
    print(f"profile: {result.profile}")
    print(f"ok: {result.ok}")
    for finding in result.findings:
        location = f" {finding.path}" if finding.path else ""
        mode = f"[{finding.mode}] " if finding.mode else ""
        print(f"- {mode}{finding.check}{location}: {finding.message}")


if __name__ == "__main__":
    raise SystemExit(main())
