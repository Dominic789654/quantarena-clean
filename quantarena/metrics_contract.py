"""Paper-facing metric contract checks for QuantArena release artifacts."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ALL_METRICS_REQUIRED_COLUMNS = (
    "experiment",
    "market",
    "mandate_dir",
    "display_name",
    "start_date",
    "end_date",
    "total_return",
    "max_drawdown",
    "volatility",
    "sharpe_ratio",
    "avg_cash_ratio",
    "avg_position_days",
    "total_trades",
    "trading_days",
)

RUN_METRIC_REQUIRED_FIELDS = (
    "total_return",
    "max_drawdown",
    "volatility",
    "sharpe_ratio",
    "avg_cash_ratio",
    "avg_position_days",
    "total_trades",
    "trading_days",
)

RUN_METRIC_OPTIONAL_BEHAVIOR_FIELDS = (
    "avg_turnover_ratio",
)

NUMERIC_CONSISTENCY_FIELDS = (
    "total_return",
    "max_drawdown",
    "volatility",
    "sharpe_ratio",
    "avg_cash_ratio",
    "avg_position_days",
    "total_trades",
    "trading_days",
)


@dataclass
class MetricsContractResult:
    """Structured result for release metric contract checks."""

    root: Path
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_check(self, name: str, passed: bool, message: str | None = None) -> None:
        self.checks[name] = passed
        if not passed and message:
            self.errors.append(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "root": str(self.root),
            "checks": self.checks,
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": self.stats,
        }


def validate_metrics_contract(root: str | Path) -> MetricsContractResult:
    """Validate paper-facing metric fields in a release-data-style bundle."""
    release_root = Path(root)
    result = MetricsContractResult(root=release_root)

    all_metrics_path = release_root / "derived" / "all_metrics.csv"
    result.add_check(
        "all_metrics_exists",
        all_metrics_path.is_file(),
        f"Missing all_metrics.csv: {all_metrics_path}",
    )
    if not result.ok:
        return result

    rows = _read_csv_rows(all_metrics_path, result)
    if rows is None:
        return result

    _validate_all_metrics_rows(rows, result)
    _validate_run_metric_files(release_root, rows, result)
    return result


def _read_csv_rows(
    path: Path,
    result: MetricsContractResult,
) -> list[dict[str, str]] | None:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
    except csv.Error as exc:
        result.add_check("all_metrics_csv_valid", False, f"Invalid CSV in {path}: {exc}")
        return None

    fieldnames = reader.fieldnames or []
    missing_columns = [name for name in ALL_METRICS_REQUIRED_COLUMNS if name not in fieldnames]
    result.add_check(
        "all_metrics_required_columns",
        not missing_columns,
        "all_metrics.csv missing required columns: " + ", ".join(missing_columns),
    )
    result.add_check("all_metrics_rows_present", bool(rows), "all_metrics.csv must contain rows")
    result.stats["all_metrics_rows"] = len(rows)
    return rows


def _validate_all_metrics_rows(
    rows: list[dict[str, str]],
    result: MetricsContractResult,
) -> None:
    missing_values: list[str] = []
    invalid_numeric: list[str] = []

    for index, row in enumerate(rows, start=2):
        row_id = _row_id(row, fallback=f"row:{index}")
        for field_name in ALL_METRICS_REQUIRED_COLUMNS:
            value = row.get(field_name)
            if value is None or value == "":
                missing_values.append(f"{row_id}:{field_name}")
                continue
            if field_name in NUMERIC_CONSISTENCY_FIELDS and _parse_number(value) is None:
                invalid_numeric.append(f"{row_id}:{field_name}={value!r}")

    result.stats["all_metrics_missing_values"] = len(missing_values)
    result.stats["all_metrics_invalid_numeric"] = len(invalid_numeric)
    result.add_check(
        "all_metrics_required_values",
        not missing_values,
        "all_metrics.csv missing required values: " + ", ".join(missing_values),
    )
    result.add_check(
        "all_metrics_numeric_values",
        not invalid_numeric,
        "all_metrics.csv has non-numeric metric values: " + ", ".join(invalid_numeric),
    )


def _validate_run_metric_files(
    release_root: Path,
    rows: list[dict[str, str]],
    result: MetricsContractResult,
) -> None:
    missing_files: list[str] = []
    missing_fields: list[str] = []
    invalid_numeric: list[str] = []
    optional_missing: list[str] = []
    inconsistent_values: list[str] = []
    run_files_checked = 0

    for row in rows:
        experiment = row.get("experiment", "")
        mandate_dir = row.get("mandate_dir", "")
        row_id = _row_id(row, fallback=f"{experiment}/{mandate_dir}")
        metrics_path = release_root / "runs" / experiment / mandate_dir / "metrics.json"
        if not metrics_path.is_file():
            missing_files.append(str(metrics_path.relative_to(release_root)))
            continue

        run_metrics = _load_run_metrics(metrics_path, result)
        if run_metrics is None:
            continue
        run_files_checked += 1

        for field_name in RUN_METRIC_REQUIRED_FIELDS:
            if field_name not in run_metrics or run_metrics.get(field_name) in ("", None):
                missing_fields.append(f"{row_id}:{field_name}")
                continue
            if field_name in NUMERIC_CONSISTENCY_FIELDS:
                run_value = _parse_number(run_metrics.get(field_name))
                if run_value is None:
                    invalid_numeric.append(f"{row_id}:{field_name}={run_metrics.get(field_name)!r}")

        for field_name in RUN_METRIC_OPTIONAL_BEHAVIOR_FIELDS:
            if field_name not in run_metrics or run_metrics.get(field_name) in ("", None):
                optional_missing.append(f"{row_id}:{field_name}")
                continue
            if _parse_number(run_metrics.get(field_name)) is None:
                invalid_numeric.append(f"{row_id}:{field_name}={run_metrics.get(field_name)!r}")

        for field_name in NUMERIC_CONSISTENCY_FIELDS:
            row_value = _parse_number(row.get(field_name))
            run_value = _parse_number(run_metrics.get(field_name))
            if row_value is None or run_value is None:
                continue
            if abs(row_value - run_value) > 1e-4:
                inconsistent_values.append(
                    f"{row_id}:{field_name} all_metrics={row_value} metrics_json={run_value}"
                )

    result.stats["run_metric_files_checked"] = run_files_checked
    result.stats["run_metric_missing_files"] = len(missing_files)
    result.stats["run_metric_missing_fields"] = len(missing_fields)
    result.stats["run_metric_invalid_numeric"] = len(invalid_numeric)
    result.stats["run_metric_optional_behavior_missing"] = len(optional_missing)
    result.stats["run_metric_inconsistent_values"] = len(inconsistent_values)
    result.add_check(
        "run_metric_files_exist",
        not missing_files,
        "Missing run-level metrics.json files: " + ", ".join(missing_files),
    )
    result.add_check(
        "run_metric_required_fields",
        not missing_fields,
        "Run-level metrics.json missing required fields: " + ", ".join(missing_fields),
    )
    result.add_check(
        "run_metric_numeric_values",
        not invalid_numeric,
        "Run-level metrics.json has non-numeric metric values: " + ", ".join(invalid_numeric),
    )
    result.add_check(
        "run_metric_values_match_all_metrics",
        not inconsistent_values,
        "Run-level metrics do not match all_metrics.csv: " + ", ".join(inconsistent_values),
    )
    if optional_missing:
        result.warnings.append(
            "Run-level optional behavior metrics missing: " + ", ".join(optional_missing)
        )


def _load_run_metrics(path: Path, result: MetricsContractResult) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.errors.append(f"Invalid JSON in {path}: {exc}")
        return None

    if not isinstance(payload, dict) or not isinstance(payload.get("metrics"), dict):
        result.errors.append(f"{path} must contain a metrics object")
        return None
    return payload["metrics"]


def _row_id(row: dict[str, str], *, fallback: str) -> str:
    experiment = row.get("experiment")
    mandate_dir = row.get("mandate_dir")
    if experiment and mandate_dir:
        return f"{experiment}/{mandate_dir}"
    return fallback


def _parse_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed
