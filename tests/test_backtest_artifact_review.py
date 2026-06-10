"""Tests for post-run backtest artifact review checks."""

from __future__ import annotations

import json
from pathlib import Path

from quantarena.backtest_artifact_review import review_multi_personality_artifacts


def _write_multi_artifacts(
    multi_dir: Path,
    *,
    daily_decisions: list[dict] | None = None,
    news_diagnostics: list[dict] | None = None,
) -> None:
    decisions = daily_decisions if daily_decisions is not None else [
        {
            "date": "2026-01-02",
            "personality": "behavioral_momentum",
            "ticker": "AAA",
            "action": "BUY",
            "shares": 1,
        }
    ]
    diagnostics = news_diagnostics if news_diagnostics is not None else []
    (multi_dir / "daily_decisions.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in decisions),
        encoding="utf-8",
    )
    (multi_dir / "news_diagnostics.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in diagnostics),
        encoding="utf-8",
    )


def _write_run(
    root: Path,
    run_id: str,
    *,
    metrics: dict,
    trades_csv: str = "date,ticker,action,shares,price\n",
    audit_lines: list[dict] | None = None,
) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metrics.json").write_text(
        json.dumps({"run_id": run_id, "market": "us", "metrics": metrics}),
        encoding="utf-8",
    )
    (run_dir / "equity_curve.csv").write_text("date,total_value\n2026-01-02,1000\n", encoding="utf-8")
    (run_dir / "trades.csv").write_text(trades_csv, encoding="utf-8")
    audit_content = ""
    if audit_lines:
        audit_content = "\n".join(json.dumps(line) for line in audit_lines) + "\n"
    (run_dir / "broker_audit.jsonl").write_text(audit_content, encoding="utf-8")


def test_review_multi_personality_artifacts_flags_trades_without_audit(tmp_path: Path):
    multi_dir = tmp_path / "reports" / "multi_personality" / "run"
    backtest_root = tmp_path / "reports" / "backtest"
    multi_dir.mkdir(parents=True)
    (multi_dir / "comparison_data.json").write_text(
        json.dumps(
            {
                "artifact_schema_version": 2,
                "personality_results": [
                    {
                        "personality": "fundamental_value",
                        "run_id": "value-run",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _write_multi_artifacts(multi_dir)
    _write_run(
        backtest_root,
        "value-run",
        metrics={"total_return": 0.1},
        trades_csv="date,ticker,action,shares,price\n2026-01-02,AAA,BUY,1,10\n",
        audit_lines=[],
    )

    review = review_multi_personality_artifacts(multi_dir, backtest_root=backtest_root)

    assert review.ok is False
    messages = [finding.message for finding in review.findings]
    assert "trades.csv contains trades but broker_audit.jsonl has no events" in messages
    assert any("specialized metrics missing" in message for message in messages)


def test_review_multi_personality_artifacts_accepts_matching_audit_and_metrics(tmp_path: Path):
    multi_dir = tmp_path / "reports" / "multi_personality" / "run"
    backtest_root = tmp_path / "reports" / "backtest"
    multi_dir.mkdir(parents=True)
    (multi_dir / "comparison_data.json").write_text(
        json.dumps(
            {
                "artifact_schema_version": 2,
                "personality_results": {
                    "behavioral_momentum": {
                        "personality": "behavioral_momentum",
                        "run_id": "momentum-run",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _write_multi_artifacts(
        multi_dir,
        news_diagnostics=[
            {
                "provider": "fmp",
                "ticker": "AAA",
                "trading_date": "2026-01-02",
                "raw_count": 0,
                "final_count": 0,
                "stages": [],
            }
        ],
    )
    _write_run(
        backtest_root,
        "momentum-run",
        metrics={
            "total_return": 0.1,
            "vol_scaling_activation_rate": 1.0,
            "crash_breaker_trigger_count": 0,
            "avg_momentum_exposure_multiplier": 1.0,
        },
        trades_csv="date,ticker,action,shares,price\n2026-01-02,AAA,BUY,1,10\n",
        audit_lines=[{"outcome": "filled", "order_id": "paper-000001"}],
    )

    review = review_multi_personality_artifacts(multi_dir, backtest_root=backtest_root)

    assert review.ok is True
    assert review.findings == []
    assert review.runs["behavioral_momentum"]["trade_count"] == 1
    assert review.runs["behavioral_momentum"]["broker_audit_count"] == 1
    assert review.artifacts["daily_decisions_count"] == 1
    assert review.artifacts["news_diagnostics_count"] == 1


def test_review_multi_personality_artifacts_requires_daily_decisions(tmp_path: Path):
    multi_dir = tmp_path / "reports" / "multi_personality" / "run"
    backtest_root = tmp_path / "reports" / "backtest"
    multi_dir.mkdir(parents=True)
    (multi_dir / "comparison_data.json").write_text(
        json.dumps(
            {
                "run_id": "comparison-run",
                "artifact_schema_version": 2,
                "personality_results": {
                    "balanced": {
                        "personality": "balanced",
                        "run_id": "balanced-run",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (multi_dir / "news_diagnostics.jsonl").write_text("", encoding="utf-8")
    _write_run(backtest_root, "balanced-run", metrics={"total_return": 0.1})

    review = review_multi_personality_artifacts(multi_dir, backtest_root=backtest_root)

    assert review.ok is False
    messages = [finding.message for finding in review.findings]
    assert "missing required artifact: daily_decisions.jsonl" in messages
    assert "daily_decisions.jsonl is missing or empty" in messages


def test_review_multi_personality_artifacts_allows_legacy_reports_without_v2_artifacts(tmp_path: Path):
    multi_dir = tmp_path / "reports" / "multi_personality" / "run"
    backtest_root = tmp_path / "reports" / "backtest"
    multi_dir.mkdir(parents=True)
    (multi_dir / "comparison_data.json").write_text(
        json.dumps(
            {
                "personality_results": {
                    "balanced": {
                        "personality": "balanced",
                        "run_id": "balanced-run",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _write_run(backtest_root, "balanced-run", metrics={"total_return": 0.1})

    review = review_multi_personality_artifacts(multi_dir, backtest_root=backtest_root)

    assert review.ok is True
    assert review.artifacts["artifact_schema_version"] == 1
    assert review.artifacts["daily_decisions_count"] == 0
    assert review.artifacts["news_diagnostics_count"] == 0
