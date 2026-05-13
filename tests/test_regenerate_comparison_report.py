"""Tests for regenerate comparison report helpers."""

import csv
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "deepfund" / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

from backtest.regenerate_comparison_report import (
    RegenerationError,
    _load_avg_position_days,
    load_existing_results,
    regenerate_report,
)


def test_load_avg_position_days_reconstructs_from_trades_csv(tmp_path):
    target_dir = tmp_path / "run"
    target_dir.mkdir()
    trades_path = target_dir / "trades.csv"

    pd.DataFrame(
        [
            {"date": "2026-01-02", "ticker": "AAA", "action": "BUY", "shares": 10, "price": 10.0, "value": 100.0, "justification": ""},
            {"date": "2026-01-06", "ticker": "AAA", "action": "SELL", "shares": 10, "price": 12.0, "value": 120.0, "justification": ""},
        ]
    ).to_csv(trades_path, index=False)

    assert _load_avg_position_days(target_dir, metrics={}) == 4.0
    assert _load_avg_position_days(target_dir, metrics={"avg_position_days": 7.5}) == 7.5


def test_load_avg_position_days_reconstructs_from_loaded_trade_rows(tmp_path):
    target_dir = tmp_path / "run"
    target_dir.mkdir()
    (target_dir / "metrics.json").write_text('{"metrics": {}}', encoding="utf-8")
    (target_dir / "equity_curve.csv").write_text("date,total_value\n", encoding="utf-8")
    (target_dir / "trades.csv").write_text(
        "\n".join(
            [
                "date,ticker,action,shares,price,value,justification",
                "2026-01-02,AAA,BUY,10,10.0,100.0,",
                "2026-01-05,AAA,SELL,not-a-number,12.0,120.0,",
                "2026-01-06,AAA,SELL,10,12.0,120.0,",
            ]
        ),
        encoding="utf-8",
    )

    assert _load_avg_position_days(target_dir, metrics={}) == 4.0


def test_load_existing_results_uses_exact_personality_run_ids_from_comparison_data(tmp_path):
    backtest_dir = tmp_path / "reports" / "backtest"
    comparison_dir = tmp_path / "reports" / "multi_personality"
    run_id = "20260409_165121_176781"
    comparison_run_dir = comparison_dir / run_id
    comparison_run_dir.mkdir(parents=True)
    backtest_dir.mkdir(parents=True)

    exact_alpha = backtest_dir / "mp_alpha_20260409_111111_000001"
    wrong_alpha = backtest_dir / "mp_alpha_20260409_222222_000002"
    exact_beta = backtest_dir / "mp_beta_20260409_111111_000003"
    wrong_beta = backtest_dir / "mp_beta_20260409_222222_000004"

    for target_dir, total_return in (
        (exact_alpha, 1.23),
        (wrong_alpha, 9.99),
        (exact_beta, -0.5),
        (wrong_beta, 8.88),
    ):
        target_dir.mkdir()
        with open(target_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "metrics": {
                        "total_return": total_return,
                        "max_drawdown": 1.0,
                        "sharpe_ratio": 0.5,
                        "total_trades": 3,
                        "win_rate": 50.0,
                        "avg_position_days": 2.0,
                        "initial_cash": 100000.0,
                    }
                },
                f,
            )

    with open(comparison_run_dir / "comparison_data.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": {"personalities": ["alpha", "beta"]},
                "personality_results": {
                    "alpha": {"run_id": exact_alpha.name},
                    "beta": {"run_id": exact_beta.name},
                },
            },
            f,
        )

    results = load_existing_results(
        run_id,
        personalities=["alpha", "beta"],
        backtest_reports_dir=backtest_dir,
        comparison_reports_dir=comparison_dir,
    )

    assert results["alpha"]["run_id"] == exact_alpha.name
    assert results["alpha"]["total_return"] == 1.23
    assert results["beta"]["run_id"] == exact_beta.name
    assert results["beta"]["total_return"] == -0.5


def test_load_existing_results_allows_metrics_only_run_artifacts(tmp_path):
    backtest_dir = tmp_path / "reports" / "backtest"
    comparison_dir = tmp_path / "reports" / "multi_personality"
    run_id = "20260409_165121_176781"
    comparison_run_dir = comparison_dir / run_id
    comparison_run_dir.mkdir(parents=True)
    backtest_dir.mkdir(parents=True)

    alpha_dir = backtest_dir / "mp_alpha_20260409_111111_000001"
    alpha_dir.mkdir()
    with open(alpha_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "metrics": {
                    "total_return": 1.23,
                    "max_drawdown": 1.0,
                    "sharpe_ratio": 0.5,
                    "total_trades": 3,
                    "win_rate": 50.0,
                    "initial_cash": 100000.0,
                }
            },
            f,
        )

    with open(comparison_run_dir / "comparison_data.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": {"personalities": ["alpha"]},
                "personality_results": {
                    "alpha": {"run_id": alpha_dir.name},
                },
            },
            f,
        )

    results = load_existing_results(
        run_id,
        personalities=["alpha"],
        backtest_reports_dir=backtest_dir,
        comparison_reports_dir=comparison_dir,
    )

    assert results["alpha"]["total_return"] == 1.23
    assert results["alpha"]["avg_position_days"] == 0.0


def test_load_existing_results_fails_on_malformed_metrics_json(tmp_path):
    backtest_dir = tmp_path / "reports" / "backtest"
    comparison_dir = tmp_path / "reports" / "multi_personality"
    run_id = "20260409_165121_176781"
    comparison_run_dir = comparison_dir / run_id
    comparison_run_dir.mkdir(parents=True)
    backtest_dir.mkdir(parents=True)

    alpha_dir = backtest_dir / "mp_alpha_20260409_111111_000001"
    alpha_dir.mkdir()
    (alpha_dir / "metrics.json").write_text("{bad json", encoding="utf-8")

    with open(comparison_run_dir / "comparison_data.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": {"personalities": ["alpha"]},
                "personality_results": {
                    "alpha": {"run_id": alpha_dir.name},
                },
            },
            f,
        )

    with pytest.raises(RegenerationError) as excinfo:
        load_existing_results(
            run_id,
            personalities=["alpha"],
            backtest_reports_dir=backtest_dir,
            comparison_reports_dir=comparison_dir,
        )

    assert "metrics.json" in str(excinfo.value)


def test_load_existing_results_fails_on_empty_metrics_payload(tmp_path):
    backtest_dir = tmp_path / "reports" / "backtest"
    comparison_dir = tmp_path / "reports" / "multi_personality"
    run_id = "20260409_165121_176781"
    comparison_run_dir = comparison_dir / run_id
    comparison_run_dir.mkdir(parents=True)
    backtest_dir.mkdir(parents=True)

    alpha_dir = backtest_dir / "mp_alpha_20260409_111111_000001"
    alpha_dir.mkdir()
    (alpha_dir / "metrics.json").write_text("{}", encoding="utf-8")

    with open(comparison_run_dir / "comparison_data.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": {"personalities": ["alpha"]},
                "personality_results": {
                    "alpha": {"run_id": alpha_dir.name},
                },
            },
            f,
        )

    with pytest.raises(RegenerationError) as excinfo:
        load_existing_results(
            run_id,
            personalities=["alpha"],
            backtest_reports_dir=backtest_dir,
            comparison_reports_dir=comparison_dir,
        )

    assert "metrics.json" in str(excinfo.value)
    assert "metrics object" in str(excinfo.value)


def test_regenerate_report_fails_when_exact_personality_run_is_missing(tmp_path):
    backtest_dir = tmp_path / "reports" / "backtest"
    comparison_dir = tmp_path / "reports" / "multi_personality"
    run_id = "20260409_165121_176781"
    comparison_run_dir = comparison_dir / run_id
    comparison_run_dir.mkdir(parents=True)
    backtest_dir.mkdir(parents=True)

    exact_alpha = backtest_dir / "mp_alpha_20260409_111111_000001"
    exact_alpha.mkdir()
    with open(exact_alpha / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "metrics": {
                    "total_return": 1.23,
                    "max_drawdown": 1.0,
                    "sharpe_ratio": 0.5,
                    "total_trades": 3,
                    "win_rate": 50.0,
                    "avg_position_days": 2.0,
                    "initial_cash": 100000.0,
                }
            },
            f,
        )

    heuristic_beta = backtest_dir / "mp_beta_20260409_222222_000004"
    heuristic_beta.mkdir()
    with open(heuristic_beta / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "metrics": {
                    "total_return": 8.88,
                    "max_drawdown": 1.0,
                    "sharpe_ratio": 0.5,
                    "total_trades": 3,
                    "win_rate": 50.0,
                    "avg_position_days": 2.0,
                    "initial_cash": 100000.0,
                }
            },
            f,
        )

    old_style_beta = backtest_dir / f"mp_beta_{run_id}"
    old_style_beta.mkdir()
    with open(old_style_beta / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "metrics": {
                    "total_return": 8.88,
                    "max_drawdown": 1.0,
                    "sharpe_ratio": 0.5,
                    "total_trades": 3,
                    "win_rate": 50.0,
                    "avg_position_days": 2.0,
                    "initial_cash": 100000.0,
                }
            },
            f,
        )

    with open(comparison_run_dir / "comparison_data.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": {
                    "personalities": ["alpha", "beta"],
                    "tickers": ["AAA"],
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-31",
                    "market": "us",
                    "trading_days": 20,
                    "initial_cash": 100000.0,
                },
                "shared_data_stats": {"cache_hits": 1},
                "total_duration": 12.3,
                "personality_results": {
                    "alpha": {"run_id": exact_alpha.name},
                    "beta": {"run_id": "mp_beta_20260409_111111_000003"},
                },
            },
            f,
        )

    with pytest.raises(RegenerationError) as excinfo:
        regenerate_report(run_id, backtest_reports_dir=backtest_dir, comparison_reports_dir=comparison_dir)

    assert "beta" in str(excinfo.value)

    assert not (comparison_run_dir / "personality_summary.csv").exists()


def test_load_existing_results_supports_mixed_format_bundle(tmp_path):
    backtest_dir = tmp_path / "reports" / "backtest"
    comparison_dir = tmp_path / "reports" / "multi_personality"
    run_id = "20260409_165121_176781"
    comparison_run_dir = comparison_dir / run_id
    comparison_run_dir.mkdir(parents=True)
    backtest_dir.mkdir(parents=True)

    exact_alpha = backtest_dir / "mp_alpha_20260409_111111_000001"
    exact_alpha.mkdir()
    with open(exact_alpha / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "metrics": {
                    "total_return": 1.23,
                    "max_drawdown": 1.0,
                    "sharpe_ratio": 0.5,
                    "total_trades": 3,
                    "win_rate": 50.0,
                    "avg_position_days": 2.0,
                    "initial_cash": 100000.0,
                }
            },
            f,
        )

    old_style_beta = backtest_dir / f"mp_beta_{run_id}"
    old_style_beta.mkdir()
    with open(old_style_beta / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "metrics": {
                    "total_return": 8.88,
                    "max_drawdown": 2.0,
                    "sharpe_ratio": 0.7,
                    "total_trades": 5,
                    "win_rate": 60.0,
                    "avg_position_days": 4.0,
                    "initial_cash": 100000.0,
                }
            },
            f,
        )

    with open(comparison_run_dir / "comparison_data.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": {"personalities": ["alpha", "beta"]},
                "personality_results": {
                    "alpha": {"run_id": exact_alpha.name},
                    "beta": {},
                },
            },
            f,
        )

    results = load_existing_results(
        run_id,
        personalities=["alpha", "beta"],
        backtest_reports_dir=backtest_dir,
        comparison_reports_dir=comparison_dir,
    )

    assert results["alpha"]["run_id"] == exact_alpha.name
    assert results["beta"]["run_id"] == old_style_beta.name
    assert results["beta"]["total_return"] == 8.88


def test_regenerate_report_outputs_consistent_recovered_behavior_metrics(tmp_path):
    backtest_dir = tmp_path / "reports" / "backtest"
    comparison_dir = tmp_path / "reports" / "multi_personality"
    run_id = "20260409_165121_176781"
    comparison_run_dir = comparison_dir / run_id
    comparison_run_dir.mkdir(parents=True)
    backtest_dir.mkdir(parents=True)

    alpha_dir = backtest_dir / "mp_alpha_20260409_111111_000001"
    alpha_dir.mkdir()
    with open(alpha_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "metrics": {
                    "total_return": 1.23,
                    "max_drawdown": 1.0,
                    "sharpe_ratio": 0.5,
                    "total_trades": 2,
                    "win_rate": 50.0,
                    "avg_position_days": 2.0,
                    "initial_cash": 100000.0,
                    "avg_turnover_ratio": 0.0,
                    "peak_turnover_ratio": 0.0,
                    "annualized_turnover_ratio": 0.0,
                    "total_turnover_ratio": 0.0,
                    "avg_cash_ratio": 0.0,
                    "avg_gross_exposure": 0.0,
                }
            },
            f,
        )

    pd.DataFrame(
        [
            {"date": "2024-01-02", "ticker": "AAA", "action": "BUY", "shares": 100, "price": 100.0, "value": 10000.0, "justification": ""},
            {"date": "2024-01-03", "ticker": "AAA", "action": "SELL", "shares": 50, "price": 100.0, "value": 5000.0, "justification": ""},
        ]
    ).to_csv(alpha_dir / "trades.csv", index=False)
    pd.DataFrame(
        [
            {"date": "2024-01-01", "total_value": 100000.0, "daily_return": 0.0, "cashflow": 100000.0},
            {"date": "2024-01-02", "total_value": 100000.0, "daily_return": 0.0, "cashflow": 90000.0},
            {"date": "2024-01-03", "total_value": 100000.0, "daily_return": 0.0, "cashflow": 95000.0},
        ]
    ).to_csv(alpha_dir / "equity_curve.csv", index=False)

    with open(comparison_run_dir / "comparison_data.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": {
                    "personalities": ["alpha"],
                    "tickers": ["AAA"],
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-31",
                    "market": "us",
                    "trading_days": 3,
                    "initial_cash": 100000.0,
                },
                "shared_data_stats": {"cache_hits": 2},
                "total_duration": 7.5,
                "personality_results": {
                    "alpha": {"run_id": alpha_dir.name},
                },
            },
            f,
        )

    regenerate_report(run_id, backtest_reports_dir=backtest_dir, comparison_reports_dir=comparison_dir)

    with open(comparison_run_dir / "comparison_data.json", "r", encoding="utf-8") as f:
        comparison_data = json.load(f)
    recovered_metrics = comparison_data["personality_results"]["alpha"]["metrics"]
    assert recovered_metrics["avg_turnover_ratio"] == 0.025
    assert recovered_metrics["avg_cash_ratio"] == 0.95
    assert recovered_metrics["avg_gross_exposure"] == 0.05

    with open(comparison_run_dir / "personality_summary.csv", "r", encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    assert row["Avg Turnover Ratio"] == "0.0250"
    assert row["Avg Cash Ratio"] == "0.9500"
    assert row["Avg Gross Exposure"] == "0.0500"

    markdown = (comparison_run_dir / "comparison_report.md").read_text(encoding="utf-8")
    assert "## 行为指标对比" in markdown
    assert "| alpha | 2.50% | 95.00% | 5.00% |" in markdown


def test_regenerate_report_preserves_failed_personality_rows(tmp_path):
    backtest_dir = tmp_path / "reports" / "backtest"
    comparison_dir = tmp_path / "reports" / "multi_personality"
    run_id = "20260409_165121_176781"
    comparison_run_dir = comparison_dir / run_id
    comparison_run_dir.mkdir(parents=True)
    backtest_dir.mkdir(parents=True)

    alpha_dir = backtest_dir / "mp_alpha_20260409_111111_000001"
    alpha_dir.mkdir()
    with open(alpha_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "metrics": {
                    "total_return": 1.23,
                    "max_drawdown": 1.0,
                    "sharpe_ratio": 0.5,
                    "total_trades": 2,
                    "win_rate": 50.0,
                    "avg_position_days": 2.0,
                    "initial_cash": 100000.0,
                }
            },
            f,
        )

    with open(comparison_run_dir / "comparison_data.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": {
                    "personalities": ["alpha", "beta"],
                    "tickers": ["AAA"],
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-31",
                    "market": "us",
                    "trading_days": 3,
                    "initial_cash": 100000.0,
                },
                "shared_data_stats": {"cache_hits": 2},
                "total_duration": 7.5,
                "personality_results": {
                    "alpha": {"run_id": alpha_dir.name, "error_count": 0},
                    "beta": {
                        "total_return": 0,
                        "max_drawdown": 0,
                        "sharpe_ratio": 0,
                        "trade_count": 0,
                        "win_rate": 0,
                        "avg_position_days": 0,
                        "duration_seconds": 12.0,
                        "error_count": 1,
                        "token_usage": {},
                    },
                },
            },
            f,
        )

    regenerate_report(run_id, backtest_reports_dir=backtest_dir, comparison_reports_dir=comparison_dir)

    with open(comparison_run_dir / "comparison_data.json", "r", encoding="utf-8") as f:
        comparison_data = json.load(f)
    failed_row = comparison_data["personality_results"]["beta"]
    assert failed_row["error_count"] == 1
    assert failed_row["run_id"] is None
    assert failed_row["duration_seconds"] == 12.0

    with open(comparison_run_dir / "personality_summary.csv", "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    beta_row = next(row for row in rows if row["Personality"] == "beta")
    assert beta_row["Error Count"] == "1"
    assert beta_row["Trade Count"] == "0"

    markdown = (comparison_run_dir / "comparison_report.md").read_text(encoding="utf-8")
    assert "### BETA 详细分析" in markdown
    assert "运行中出现 1 个错误" in markdown
