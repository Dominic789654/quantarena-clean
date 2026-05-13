"""Tests for the paper-facing release metric contract."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from quantarena.metrics_contract import validate_metrics_contract


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "release_metrics_contract"


def test_metrics_contract_accepts_fixture_bundle():
    result = validate_metrics_contract(FIXTURE_ROOT)

    assert result.ok is True
    assert result.checks["all_metrics_required_columns"] is True
    assert result.checks["all_metrics_required_values"] is True
    assert result.checks["all_metrics_numeric_values"] is True
    assert result.checks["run_metric_files_exist"] is True
    assert result.checks["run_metric_required_fields"] is True
    assert result.checks["run_metric_values_match_all_metrics"] is True
    assert result.stats["all_metrics_rows"] == 3
    assert result.stats["run_metric_files_checked"] == 3
    assert result.stats["run_metric_optional_behavior_missing"] == 1
    assert result.warnings == [
        "Run-level optional behavior metrics missing: "
        "exp1_caseStudy_us_6m/macro_tactical:avg_turnover_ratio"
    ]


def test_metrics_contract_rejects_missing_table_column(tmp_path: Path):
    _copy_fixture(tmp_path)
    all_metrics_path = tmp_path / "derived" / "all_metrics.csv"
    rows = list(csv.DictReader(all_metrics_path.open(newline="", encoding="utf-8")))
    fieldnames = [
        field_name for field_name in rows[0].keys() if field_name != "avg_position_days"
    ]
    with all_metrics_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fieldnames} for row in rows)

    result = validate_metrics_contract(tmp_path)

    assert result.ok is False
    assert result.checks["all_metrics_required_columns"] is False
    assert "avg_position_days" in "\n".join(result.errors)


def test_metrics_contract_rejects_run_level_mismatch(tmp_path: Path):
    _copy_fixture(tmp_path)
    metrics_path = tmp_path / "runs" / "exp1_caseStudy_cn_6m" / "equal_weight" / "metrics.json"
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    payload["metrics"]["total_return"] = 99.0
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_metrics_contract(tmp_path)

    assert result.ok is False
    assert result.checks["run_metric_values_match_all_metrics"] is False
    assert "total_return" in "\n".join(result.errors)


def test_metrics_contract_rejects_non_numeric_run_metric(tmp_path: Path):
    _copy_fixture(tmp_path)
    metrics_path = tmp_path / "runs" / "exp1_caseStudy_cn_6m" / "equal_weight" / "metrics.json"
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    payload["metrics"]["total_return"] = "not-a-number"
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_metrics_contract(tmp_path)

    assert result.ok is False
    assert result.checks["run_metric_numeric_values"] is False
    assert "total_return" in "\n".join(result.errors)


def test_metrics_contract_rejects_non_finite_table_metric(tmp_path: Path):
    _copy_fixture(tmp_path)
    all_metrics_path = tmp_path / "derived" / "all_metrics.csv"
    rows = list(csv.DictReader(all_metrics_path.open(newline="", encoding="utf-8")))
    rows[0]["sharpe_ratio"] = "NaN"
    with all_metrics_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = validate_metrics_contract(tmp_path)

    assert result.ok is False
    assert result.checks["all_metrics_numeric_values"] is False
    assert "sharpe_ratio" in "\n".join(result.errors)


def test_metrics_contract_rejects_missing_required_run_field(tmp_path: Path):
    _copy_fixture(tmp_path)
    metrics_path = tmp_path / "runs" / "exp1_caseStudy_cn_6m" / "low_volatility" / "metrics.json"
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    del payload["metrics"]["avg_cash_ratio"]
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_metrics_contract(tmp_path)

    assert result.ok is False
    assert result.checks["run_metric_required_fields"] is False
    assert "avg_cash_ratio" in "\n".join(result.errors)


def test_metrics_contract_checks_optional_local_release_bundle_if_present():
    local_bundle = Path(__file__).resolve().parents[1] / "release_data"
    if not local_bundle.exists():
        pytest.skip("local release_data bundle is not present in this checkout")

    result = validate_metrics_contract(local_bundle)

    assert result.ok is True
    assert result.stats["all_metrics_rows"] >= 3
    assert result.stats["run_metric_files_checked"] >= 3


def _copy_fixture(target: Path) -> None:
    for source in FIXTURE_ROOT.rglob("*"):
        relative_path = source.relative_to(FIXTURE_ROOT)
        destination = target / relative_path
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
