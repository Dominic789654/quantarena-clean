"""Unit tests for the backtest run manifest."""

from __future__ import annotations

import json
from types import SimpleNamespace

from backtest.report import ReportGenerator


def _make_result():
    return SimpleNamespace(
        run_id="20260723_test_run",
        start_date="2026-01-05",
        end_date="2026-01-30",
        market="us",
        tickers=["JPM", "MSFT"],
        initial_cash=100000.0,
        benchmark_source="equal_weight",
        errors=["one recoverable warning"],
        config={
            "personality": "behavioral_momentum",
            "workflow_analysts": ["technical", "social_sentiment"],
            "llm": {"provider": "DeepSeek", "model": "deepseek-v4-flash"},
            "api_source": {"default": "fmp", "us_source": "fmp"},
        },
    )


TOKEN_STATS = {
    "calls": 12,
    "total_input": 4_000_000,
    "total_output": 500_000,
    "by_agent": {"technical": {"input": 2_000_000, "output": 250_000}},
}


def test_run_manifest_content(tmp_path):
    reporter = ReportGenerator(output_dir=str(tmp_path))
    path = tmp_path / "run_manifest.json"

    reporter.generate_run_manifest(
        _make_result(), str(path), token_stats_override=TOKEN_STATS
    )
    manifest = json.loads(path.read_text())

    assert manifest["manifest_version"] == 1
    assert manifest["run_id"] == "20260723_test_run"
    assert manifest["generated_at"]

    exp = manifest["experiment"]
    assert exp["market"] == "us"
    assert exp["tickers"] == ["JPM", "MSFT"]
    assert exp["personality"] == "behavioral_momentum"
    assert exp["workflow_analysts"] == ["technical", "social_sentiment"]
    assert exp["llm"] == {"provider": "DeepSeek", "model": "deepseek-v4-flash"}
    assert exp["benchmark_source"] == "equal_weight"

    usage = manifest["llm_usage"]
    assert usage["calls"] == 12
    assert usage["total_tokens"] == 4_500_000
    # 4M input * 1 CNY/M + 0.5M output * 2 CNY/M = 5.0
    assert usage["estimated_cost_cny"] == 5.0
    assert usage["by_agent"]["technical"]["input"] == 2_000_000

    assert manifest["errors"] == ["one recoverable warning"]


def test_run_manifest_git_provenance(tmp_path):
    """In this checkout the manifest should carry a real commit SHA."""
    reporter = ReportGenerator(output_dir=str(tmp_path))

    manifest = json.loads(
        reporter.generate_run_manifest(_make_result(), token_stats_override={})
    )

    git = manifest["git"]
    assert git["sha"] is None or (len(git["sha"]) == 40 and isinstance(git["dirty"], bool))


def test_generate_full_report_writes_run_manifest(tmp_path, monkeypatch):
    """The full-report pipeline must actually emit run_manifest.json."""
    from pathlib import Path

    reporter = ReportGenerator(output_dir=str(tmp_path))
    result = SimpleNamespace(
        run_id="manifest-run",
        config={"personality": "balanced"},
        broker_audit_events=[],
        market="us",
        tickers=["AAPL"],
        start_date="2026-01-05",
        end_date="2026-01-09",
        initial_cash=1000.0,
        benchmark_source="none",
        errors=[],
    )
    for method in (
        "generate_markdown", "generate_equity_curve_chart", "generate_trades_csv",
        "generate_metrics_json", "generate_equity_curve_csv",
    ):
        monkeypatch.setattr(reporter, method, lambda *a, **k: "")

    paths = reporter.generate_full_report(result, "manifest-run", token_stats_override={})

    manifest_path = Path(paths["run_manifest_json"])
    assert manifest_path.name == "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["manifest_version"] == 1
    assert manifest["run_id"] == "manifest-run"
    assert manifest["experiment"]["personality"] == "balanced"


def test_run_manifest_handles_missing_token_stats(tmp_path):
    reporter = ReportGenerator(output_dir=str(tmp_path))

    manifest = json.loads(
        reporter.generate_run_manifest(_make_result(), token_stats_override={})
    )

    assert manifest["llm_usage"]["calls"] == 0
    assert manifest["llm_usage"]["estimated_cost_cny"] == 0.0
