"""Tests for paper broker audit report artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from backtest.report import ReportGenerator


def test_generate_broker_audit_jsonl_writes_events(tmp_path: Path):
    result = SimpleNamespace(
        broker_audit_events=[
            {
                "date": "2026-01-02",
                "symbol": "AAA",
                "outcome": "filled",
                "order_id": "paper-000001",
                "fill_id": "fill-000001",
                "cash_before": 1000.0,
                "cash_after": 990.0,
            }
        ]
    )
    output_path = tmp_path / "broker_audit.jsonl"

    content = ReportGenerator(output_dir=str(tmp_path)).generate_broker_audit_jsonl(
        result,
        str(output_path),
    )

    assert output_path.read_text(encoding="utf-8") == content
    assert content.endswith("\n")
    assert json.loads(content) == result.broker_audit_events[0]


def test_generate_broker_audit_jsonl_writes_empty_file_when_no_events(tmp_path: Path):
    result = SimpleNamespace(broker_audit_events=[])
    output_path = tmp_path / "broker_audit.jsonl"

    content = ReportGenerator(output_dir=str(tmp_path)).generate_broker_audit_jsonl(
        result,
        str(output_path),
    )

    assert content == ""
    assert output_path.read_text(encoding="utf-8") == ""


def test_generate_full_report_includes_broker_audit_path(tmp_path: Path, monkeypatch):
    generator = ReportGenerator(output_dir=str(tmp_path))
    result = SimpleNamespace(
        run_id="audit-run",
        config={},
        broker_audit_events=[],
    )

    monkeypatch.setattr(generator, "generate_markdown", lambda *args, **kwargs: "")
    monkeypatch.setattr(generator, "generate_equity_curve_chart", lambda *args, **kwargs: "")
    monkeypatch.setattr(generator, "generate_trades_csv", lambda *args, **kwargs: "")
    monkeypatch.setattr(generator, "generate_metrics_json", lambda *args, **kwargs: "")
    monkeypatch.setattr(generator, "generate_equity_curve_csv", lambda *args, **kwargs: "")

    paths = generator.generate_full_report(result, "audit-run")

    assert paths["broker_audit_jsonl"].endswith("broker_audit.jsonl")
    assert Path(paths["broker_audit_jsonl"]).read_text(encoding="utf-8") == ""
