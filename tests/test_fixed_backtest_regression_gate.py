"""Tests for the fixed backtest regression gate."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from quantarena import fixed_backtest_regression_gate
from quantarena.fixed_backtest_regression_gate import evaluate_fixed_backtest_summary


BASELINE = Path("tests/fixtures/fixed_backtest_data/fixed_backtest_regression_baseline.json")
PERSONALITIES = [
    "macro_tactical",
    "fundamental_value",
    "behavioral_momentum",
    "smart_beta_passive",
    "equal_weight_index",
]


def test_simple_summary_matches_regression_baseline(tmp_path: Path):
    summary_path = _write_simple_summary(tmp_path)

    result = evaluate_fixed_backtest_summary(
        summary_path=summary_path,
        baseline_path=BASELINE,
        profile="simple",
    )

    assert result.ok is True
    assert result.findings == ()


def test_metric_drift_fails_with_structured_finding(tmp_path: Path):
    summary_path = _write_simple_summary(tmp_path, total_return=1.0)

    result = evaluate_fixed_backtest_summary(
        summary_path=summary_path,
        baseline_path=BASELINE,
        profile="simple",
    )

    assert result.ok is False
    assert result.findings[0].check == "metric"
    assert result.findings[0].mode == "simple"
    assert result.findings[0].path == "metrics.total_return"


def test_missing_required_mode_fails(tmp_path: Path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps({"ok": True, "mode": "simple", "runs": []}),
        encoding="utf-8",
    )

    result = evaluate_fixed_backtest_summary(
        summary_path=summary_path,
        baseline_path=BASELINE,
        profile="simple",
    )

    assert result.ok is False
    assert result.findings[0].check == "required_mode"
    assert result.findings[0].mode == "simple"


def test_multi_summary_validates_personalities_and_diagnostics(tmp_path: Path):
    summary_path = _write_multi_summary(tmp_path)

    result = evaluate_fixed_backtest_summary(
        summary_path=summary_path,
        baseline_path=BASELINE,
        profile="multi",
    )

    assert result.ok is True
    assert result.findings == ()


def test_multi_summary_fails_missing_benchmark_cache_hit(tmp_path: Path):
    summary_path = _write_multi_summary(tmp_path, benchmark_status="miss")

    result = evaluate_fixed_backtest_summary(
        summary_path=summary_path,
        baseline_path=BASELINE,
        profile="multi",
    )

    assert result.ok is False
    assert any(finding.check == "benchmark_cache_hit" for finding in result.findings)


def test_cli_can_run_benchmark_then_evaluate(monkeypatch, tmp_path: Path, capsys):
    summary_path = _write_simple_summary(tmp_path)

    def fake_run_fixed_backtest_benchmark(*, mode, config):
        assert mode == "simple"
        assert config.news_replay_path == tmp_path / "news.jsonl"
        assert config.benchmark_cache_dir == tmp_path / "benchmark_cache"
        return SimpleNamespace(summary_path=summary_path)

    monkeypatch.setattr(
        fixed_backtest_regression_gate,
        "run_fixed_backtest_benchmark",
        fake_run_fixed_backtest_benchmark,
    )

    exit_code = fixed_backtest_regression_gate.main(
        [
            "--mode",
            "simple",
            "--baseline",
            str(BASELINE),
            "--news-replay-fixture",
            str(tmp_path / "news.jsonl"),
            "--benchmark-cache-dir",
            str(tmp_path / "benchmark_cache"),
            "--json",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["ok"] is True
    assert output["profile"] == "simple"


def _write_simple_summary(tmp_path: Path, *, total_return: float = -0.18) -> Path:
    report_dir = tmp_path / "simple_run"
    report_dir.mkdir()
    dashboard_path = report_dir / "dashboard.html"
    dashboard_path.write_text("<html></html>", encoding="utf-8")
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "ok": True,
                "mode": "simple",
                "runs": [
                    {
                        "mode": "simple",
                        "ok": True,
                        "report_dir": str(report_dir),
                        "dashboard_path": str(dashboard_path),
                        "benchmark_source": "equal_weight_basket",
                        "metrics": {
                            "total_return": total_return,
                            "final_value": 9981.77,
                            "max_drawdown": 0.26,
                            "sharpe_ratio": -6.4,
                            "total_trades": 2,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return summary_path


def _write_multi_summary(tmp_path: Path, *, benchmark_status: str = "hit") -> Path:
    report_dir = tmp_path / "multi_run"
    report_dir.mkdir()
    news_path = report_dir / "news_diagnostics.jsonl"
    news_path.write_text(
        json.dumps({"ticker": "AAPL", "final_count": 1}) + "\n",
        encoding="utf-8",
    )
    benchmark_path = report_dir / "benchmark_diagnostics.jsonl"
    benchmark_path.write_text(
        json.dumps({"index_code": "^GSPC", "provider": "cache", "status": benchmark_status}) + "\n",
        encoding="utf-8",
    )
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "ok": True,
                "mode": "multi",
                "runs": [
                    {
                        "mode": "multi",
                        "ok": True,
                        "report_dir": str(report_dir),
                        "artifact_review": {"ok": True, "findings": []},
                        "metrics": {
                            "personality_summary": [
                                {"Personality": personality, "Error Count": "0"}
                                for personality in PERSONALITIES
                            ]
                        },
                        "news_diagnostics_paths": [str(news_path)],
                        "benchmark_diagnostics_paths": [str(benchmark_path)],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return summary_path
