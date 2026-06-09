"""Tests for pure report artifact loaders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantarena.report_artifacts import load_run_report_artifacts


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "report_artifacts"


def test_load_run_report_artifacts_reads_complete_fixture():
    artifacts = load_run_report_artifacts(FIXTURE_ROOT / "run_complete")

    assert artifacts.ok is True
    assert artifacts.run_id == "fixture_run"
    assert artifacts.market == "us"
    assert artifacts.trading_days == 3
    assert artifacts.trade_count == 2
    assert artifacts.broker_audit == []
    assert artifacts.broker_audit_count == 0
    assert artifacts.metrics["total_return"] == 1.5
    assert artifacts.equity_curve[1]["total_value"] == "100800.0"
    assert artifacts.trades[0]["ticker"] == "AAPL"

    summary = artifacts.summary()
    assert summary["ok"] is True
    assert summary["run_id"] == "fixture_run"
    assert summary["trading_days"] == 3
    assert summary["trade_count"] == 2
    assert summary["broker_audit_count"] == 0
    assert summary["metric_keys"] == [
        "avg_cash_ratio",
        "max_drawdown",
        "sharpe_ratio",
        "total_return",
    ]
    assert summary["errors"] == []


def test_load_run_report_artifacts_reports_missing_required_file():
    artifacts = load_run_report_artifacts(FIXTURE_ROOT / "run_missing_optional")

    assert artifacts.ok is False
    assert artifacts.run_id == "missing_optional"
    assert artifacts.trading_days == 1
    assert artifacts.trade_count == 0
    assert len(artifacts.errors) == 1
    assert artifacts.errors[0].path.name == "trades.csv"
    assert artifacts.errors[0].message == "missing required artifact"
    assert artifacts.summary()["errors"][0]["message"] == "missing required artifact"


def test_load_run_report_artifacts_reads_optional_broker_audit_jsonl(tmp_path: Path):
    (tmp_path / "metrics.json").write_text(
        json.dumps({"run_id": "audit-fixture", "market": "us", "metrics": {"total_return": 1.0}}),
        encoding="utf-8",
    )
    (tmp_path / "equity_curve.csv").write_text("date,total_value\n2026-01-02,1000\n", encoding="utf-8")
    (tmp_path / "trades.csv").write_text("date,ticker,action\n2026-01-02,AAA,BUY\n", encoding="utf-8")
    (tmp_path / "broker_audit.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"order_id": "paper-000001", "outcome": "filled"}),
                json.dumps({"order_id": None, "outcome": "rejected", "rejection_source": "risk_gate"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = load_run_report_artifacts(tmp_path)

    assert artifacts.ok is True
    assert artifacts.broker_audit_count == 2
    assert artifacts.broker_audit[0]["order_id"] == "paper-000001"
    assert artifacts.broker_audit[1]["rejection_source"] == "risk_gate"
    assert artifacts.summary()["broker_audit_count"] == 2


def test_load_run_report_artifacts_reports_invalid_metrics_json(tmp_path: Path):
    (tmp_path / "metrics.json").write_text("{bad json", encoding="utf-8")
    (tmp_path / "equity_curve.csv").write_text("date,total_value\n", encoding="utf-8")
    (tmp_path / "trades.csv").write_text("date,ticker\n", encoding="utf-8")

    artifacts = load_run_report_artifacts(tmp_path)

    assert artifacts.ok is False
    assert artifacts.metrics_payload == {}
    assert artifacts.metrics == {}
    assert artifacts.errors[0].path.name == "metrics.json"
    assert artifacts.errors[0].message.startswith("invalid JSON")


def test_load_run_report_artifacts_reports_unreadable_metrics_json(tmp_path: Path):
    (tmp_path / "metrics.json").write_bytes(b"\xff\xfe\x00")
    (tmp_path / "equity_curve.csv").write_text("date,total_value\n", encoding="utf-8")
    (tmp_path / "trades.csv").write_text("date,ticker\n", encoding="utf-8")

    artifacts = load_run_report_artifacts(tmp_path)

    assert artifacts.ok is False
    assert artifacts.metrics_payload == {}
    assert artifacts.errors[0].path.name == "metrics.json"
    assert artifacts.errors[0].message.startswith("unable to read JSON")


def test_load_run_report_artifacts_requires_metrics_object(tmp_path: Path):
    (tmp_path / "metrics.json").write_text(
        json.dumps({"run_id": "bad", "metrics": []}),
        encoding="utf-8",
    )
    (tmp_path / "equity_curve.csv").write_text("date,total_value\n", encoding="utf-8")
    (tmp_path / "trades.csv").write_text("date,ticker\n", encoding="utf-8")

    artifacts = load_run_report_artifacts(tmp_path)

    assert artifacts.ok is False
    assert artifacts.run_id == "bad"
    assert artifacts.metrics == {}
    assert any("metrics object" in error.message for error in artifacts.errors)


def test_load_run_report_artifacts_reports_missing_csv_header(tmp_path: Path):
    (tmp_path / "metrics.json").write_text(
        json.dumps({"run_id": "bad-csv", "metrics": {"total_return": 1.0}}),
        encoding="utf-8",
    )
    (tmp_path / "equity_curve.csv").write_text("", encoding="utf-8")
    (tmp_path / "trades.csv").write_text("date,ticker\n", encoding="utf-8")

    artifacts = load_run_report_artifacts(tmp_path)

    assert artifacts.ok is False
    assert any(error.path.name == "equity_curve.csv" for error in artifacts.errors)
    assert any(error.message == "CSV header is missing" for error in artifacts.errors)


def test_load_run_report_artifacts_reports_unreadable_csv(tmp_path: Path):
    (tmp_path / "metrics.json").write_text(
        json.dumps({"run_id": "bad-csv", "metrics": {"total_return": 1.0}}),
        encoding="utf-8",
    )
    (tmp_path / "equity_curve.csv").write_bytes(b"\xff\xfe\x00")
    (tmp_path / "trades.csv").write_text("date,ticker\n", encoding="utf-8")

    artifacts = load_run_report_artifacts(tmp_path)

    assert artifacts.ok is False
    assert artifacts.equity_curve == []
    assert any(error.path.name == "equity_curve.csv" for error in artifacts.errors)
    assert any(error.message.startswith("unable to read CSV") for error in artifacts.errors)


def test_load_run_report_artifacts_checks_optional_local_release_bundle_if_present():
    local_run = (
        Path(__file__).resolve().parents[1]
        / "release_data"
        / "runs"
        / "exp1_caseStudy_cn_6m"
        / "equal_weight"
    )
    if not local_run.exists():
        pytest.skip("local release_data run artifact is not present in this checkout")

    artifacts = load_run_report_artifacts(local_run)

    assert artifacts.ok is True
    assert artifacts.trading_days >= 1
    assert artifacts.trade_count >= 1
    assert "total_return" in artifacts.metrics
