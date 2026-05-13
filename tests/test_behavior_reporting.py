"""Tests for behavior metric reporting output."""

import csv
from pathlib import Path
from types import SimpleNamespace

from backtest.multi_personality_engine import MultiPersonalityComparison, PersonalityResult
from backtest.portfolio_tracker import PortfolioTracker
from backtest.report_metric_fallbacks import enrich_behavior_metrics
from backtest.report import ReportGenerator


def test_markdown_report_includes_behavior_metrics_section(tmp_path: Path):
    tracker = PortfolioTracker(initial_cash=100000.0, tickers=["AAA"])
    tracker.record_snapshot(
        "2024-01-01",
        50000.0,
        positions={"AAA": {"shares": 50, "value": 50000.0}},
        prices={"AAA": 1000.0},
    )
    result = SimpleNamespace(
        run_id="test-run",
        start_date="2024-01-01",
        end_date="2024-01-05",
        market="us",
        tickers=["AAA"],
        initial_cash=100000.0,
        tracker=tracker,
        config={},
        metrics={
            "initial_cash": 100000.0,
            "final_value": 100000.0,
            "total_return": 0.0,
            "annualized_return": 0.0,
            "trading_days": 1,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_duration": 0,
            "volatility": 0.0,
            "win_rate": 0.0,
            "avg_cash_ratio": 0.5,
            "avg_gross_exposure": 0.5,
            "avg_turnover_ratio": 0.1,
            "annualized_turnover_ratio": 25.2,
            "calmar_ratio": 0.0,
            "cvar_95": 0.0,
        },
        errors=[],
    )
    report = ReportGenerator(output_dir=str(tmp_path)).generate_markdown(result)
    assert "## Behavior Metrics" in report
    assert "Avg Cash Ratio" in report
    assert "Avg Gross Exposure" in report
    assert "Annualized Turnover Ratio" in report
    assert "CVaR (95%)" in report


def test_multi_personality_behavior_metrics_table_and_csv_include_behavior_fields(tmp_path: Path):
    tracker = PortfolioTracker(initial_cash=100000.0)
    dummy_result = SimpleNamespace(run_id="backtest-demo", metrics={
        "avg_turnover_ratio": 0.12,
        "avg_cash_ratio": 0.33,
        "avg_gross_exposure": 0.67,
        "value_consistency_score": 0.75,
        "vol_scaling_activation_rate": 0.5,
        "crash_breaker_trigger_count": 1.0,
    })
    personality_result = PersonalityResult(
        personality="fundamental_value",
        result=dummy_result,
        total_return=1.0,
        max_drawdown=2.0,
        sharpe_ratio=0.5,
        trade_count=3,
        win_rate=0.5,
        avg_position_days=4.0,
    )
    comparison = MultiPersonalityComparison(
        run_id="cmp-demo",
        start_date="2024-01-01",
        end_date="2024-01-05",
        tickers=["AAA"],
        market="us",
        trading_days=5,
        personality_results={"fundamental_value": personality_result},
    )

    generator = SimpleNamespace(
        comparison=comparison,
        initial_cash=100000.0,
        analysts=["fundamental"],
        _resolve_behavior_metrics=MultiPersonalityComparisonReporterMixin.MultiPersonalityBacktest._resolve_behavior_metrics,  # type: ignore[attr-defined]
    )

    behavior_table = MultiPersonalityComparisonReporterMixin._generate_behavior_metrics_table(generator)  # type: ignore[name-defined]
    assert "行为诊断指标" in behavior_table
    assert "价值一致性" in behavior_table

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    MultiPersonalityComparisonReporterMixin._generate_csv_summary(generator, report_dir)  # type: ignore[name-defined]
    csv_text = (report_dir / "personality_summary.csv").read_text(encoding="utf-8")
    assert "Avg Turnover Ratio" in csv_text
    assert "Avg Cash Ratio" in csv_text
    assert "Avg Gross Exposure" in csv_text


class MultiPersonalityComparisonReporterMixin:
    """Thin mixin shim to call reporter helpers on the engine methods."""

    from backtest.multi_personality_engine import MultiPersonalityBacktest

    _generate_behavior_metrics_table = MultiPersonalityBacktest._generate_behavior_metrics_table
    _generate_trading_behavior_table = MultiPersonalityBacktest._generate_trading_behavior_table
    _generate_csv_summary = MultiPersonalityBacktest._generate_csv_summary


def test_multi_personality_trading_behavior_table_uses_report_artifact_loader(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report_dir = Path("reports/backtest/backtest-demo")
    report_dir.mkdir(parents=True)
    (report_dir / "metrics.json").write_text('{"metrics": {"total_return": 0.0}}', encoding="utf-8")
    (report_dir / "equity_curve.csv").write_text("date,total_value\n2024-01-01,100000.0\n", encoding="utf-8")
    with open(report_dir / "trades.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "ticker", "action", "shares", "price", "value", "justification"])
        writer.writerow(["2024-01-02", "AAA", "BUY", 10, 100.0, 1000.0, ""])
        writer.writerow(["2024-01-03", "AAA", "SELL", 5, 101.0, 505.0, ""])
        writer.writerow(["2024-01-04", "AAA", "HOLD", 0, 101.0, 0.0, ""])

    dummy_result = SimpleNamespace(run_id="backtest-demo", metrics={})
    personality_result = PersonalityResult(
        personality="fundamental_value",
        result=dummy_result,
        total_return=1.0,
        max_drawdown=2.0,
        sharpe_ratio=0.5,
        trade_count=99,
        win_rate=0.5,
        avg_position_days=4.0,
    )
    comparison = MultiPersonalityComparison(
        run_id="cmp-demo",
        start_date="2024-01-01",
        end_date="2024-01-05",
        tickers=["AAA"],
        market="us",
        trading_days=3,
        personality_results={"fundamental_value": personality_result},
    )

    generator = SimpleNamespace(comparison=comparison)
    behavior_table = MultiPersonalityComparisonReporterMixin._generate_trading_behavior_table(generator)  # type: ignore[name-defined]

    assert "| fundamental_value | 3 | 1 | 1 | 1.00 | 4.0 天 |" in behavior_table


def test_multi_personality_trading_behavior_table_tolerates_blank_trade_actions(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    report_dir = Path("reports/backtest/backtest-demo")
    report_dir.mkdir(parents=True)
    (report_dir / "metrics.json").write_text('{"metrics": {"total_return": 0.0}}', encoding="utf-8")
    (report_dir / "equity_curve.csv").write_text("date,total_value\n2024-01-01,100000.0\n", encoding="utf-8")
    (report_dir / "trades.csv").write_text(
        "date,ticker,action,shares,price,value,justification\n"
        "2024-01-02,AAA,BUY,10,100.0,1000.0,\n"
        "2024-01-03,AAA,,5,101.0,505.0,\n",
        encoding="utf-8",
    )

    dummy_result = SimpleNamespace(run_id="backtest-demo", metrics={})
    personality_result = PersonalityResult(
        personality="fundamental_value",
        result=dummy_result,
        total_return=1.0,
        max_drawdown=2.0,
        sharpe_ratio=0.5,
        trade_count=99,
        win_rate=0.5,
        avg_position_days=4.0,
    )
    comparison = MultiPersonalityComparison(
        run_id="cmp-demo",
        start_date="2024-01-01",
        end_date="2024-01-05",
        tickers=["AAA"],
        market="us",
        trading_days=2,
        personality_results={"fundamental_value": personality_result},
    )

    generator = SimpleNamespace(comparison=comparison)
    behavior_table = MultiPersonalityComparisonReporterMixin._generate_trading_behavior_table(generator)  # type: ignore[name-defined]

    assert "| fundamental_value | 2 | 1 | 0 | 1.00 | 4.0 天 |" in behavior_table


def test_enrich_behavior_metrics_recovers_turnover_from_report_artifacts(tmp_path: Path):
    report_dir = tmp_path / "backtest-run"
    report_dir.mkdir()

    with open(report_dir / "trades.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "ticker", "action", "shares", "price", "value", "justification"])
        writer.writerow(["2024-01-02", "AAA", "BUY", 100, 100.0, 10000.0, ""])
        writer.writerow(["2024-01-03", "AAA", "SELL", 50, 100.0, 5000.0, ""])

    with open(report_dir / "equity_curve.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "total_value", "daily_return", "cashflow"])
        writer.writerow(["2024-01-01", 100000.0, 0.0, 100000.0])
        writer.writerow(["2024-01-02", 100000.0, 0.0, 90000.0])
        writer.writerow(["2024-01-03", 100000.0, 0.0, 95000.0])

    metrics = enrich_behavior_metrics({}, report_dir)

    assert metrics["avg_turnover_ratio"] == 0.025
    assert metrics["peak_turnover_ratio"] == 0.05
    assert metrics["annualized_turnover_ratio"] == 6.3
    assert metrics["total_turnover_ratio"] == 0.075
    assert metrics["avg_cash_ratio"] == 0.95
    assert metrics["avg_gross_exposure"] == 0.05


def test_enrich_behavior_metrics_converts_loader_rows_to_numeric_values(tmp_path: Path):
    report_dir = tmp_path / "backtest-run"
    report_dir.mkdir()

    with open(report_dir / "trades.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "ticker", "action", "shares", "price", "value", "justification"])
        writer.writerow(["2024-01-02", "AAA", "BUY", "100", "100.0", "10000.0", ""])

    with open(report_dir / "equity_curve.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "total_value", "daily_return", "cashflow"])
        writer.writerow(["2024-01-01", "100000.0", "0.0", "100000.0"])
        writer.writerow(["2024-01-02", "100000.0", "0.0", "90000.0"])

    metrics = enrich_behavior_metrics({}, report_dir)

    assert metrics["peak_turnover_ratio"] == 0.05
    assert metrics["avg_cash_ratio"] == 0.95


def test_enrich_behavior_metrics_preserves_pandas_style_na_handling(tmp_path: Path):
    report_dir = tmp_path / "backtest-run"
    report_dir.mkdir()

    with open(report_dir / "trades.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "ticker", "action", "shares", "price", "value", "justification"])
        writer.writerow(["2024-01-02", "AAA", "BUY", "100", "100.0", "10000.0", ""])

    with open(report_dir / "equity_curve.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "total_value", "daily_return", "cashflow"])
        writer.writerow(["2024-01-01", "100000.0", "0.0", "100000.0"])
        writer.writerow(["2024-01-02", "NA", "0.0", "nan"])
        writer.writerow(["2024-01-03", "100000.0", "0.0", "95000.0"])

    metrics = enrich_behavior_metrics({}, report_dir)

    assert metrics["avg_turnover_ratio"] == 0.0167
    assert metrics["avg_cash_ratio"] == 0.975
    assert metrics["avg_gross_exposure"] == 0.025


def test_enrich_behavior_metrics_uses_initial_cash_for_first_day_turnover(tmp_path: Path):
    report_dir = tmp_path / "backtest-run"
    report_dir.mkdir()

    with open(report_dir / "trades.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "ticker", "action", "shares", "price", "value", "justification"])
        writer.writerow(["2024-01-01", "AAA", "BUY", 200, 100.0, 20000.0, ""])

    with open(report_dir / "equity_curve.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "total_value", "daily_return", "cashflow"])
        writer.writerow(["2024-01-01", 80000.0, 0.0, 80000.0])
        writer.writerow(["2024-01-02", 80000.0, 0.0, 80000.0])

    metrics = enrich_behavior_metrics({"initial_cash": 100000.0}, report_dir)

    assert metrics["avg_turnover_ratio"] == 0.05
    assert metrics["peak_turnover_ratio"] == 0.1
    assert metrics["annualized_turnover_ratio"] == 12.6
    assert metrics["total_turnover_ratio"] == 0.1


def test_enrich_behavior_metrics_overrides_stale_zero_turnover_placeholders(tmp_path: Path):
    report_dir = tmp_path / "backtest-run"
    report_dir.mkdir()

    with open(report_dir / "trades.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "ticker", "action", "shares", "price", "value", "justification"])
        writer.writerow(["2024-01-02", "AAA", "BUY", 100, 100.0, 10000.0, ""])
        writer.writerow(["2024-01-03", "AAA", "SELL", 50, 100.0, 5000.0, ""])

    with open(report_dir / "equity_curve.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "total_value", "daily_return", "cashflow"])
        writer.writerow(["2024-01-01", 100000.0, 0.0, 100000.0])
        writer.writerow(["2024-01-02", 100000.0, 0.0, 90000.0])
        writer.writerow(["2024-01-03", 100000.0, 0.0, 95000.0])

    metrics = enrich_behavior_metrics(
        {
            "initial_cash": 100000.0,
            "avg_turnover_ratio": 0.0,
            "peak_turnover_ratio": 0.0,
            "annualized_turnover_ratio": 0.0,
            "total_turnover_ratio": 0.0,
        },
        report_dir,
    )

    assert metrics["avg_turnover_ratio"] == 0.025
    assert metrics["peak_turnover_ratio"] == 0.05
    assert metrics["annualized_turnover_ratio"] == 6.3
    assert metrics["total_turnover_ratio"] == 0.075


def test_enrich_behavior_metrics_overrides_stale_zero_exposure_placeholders(tmp_path: Path):
    report_dir = tmp_path / "backtest-run"
    report_dir.mkdir()

    with open(report_dir / "equity_curve.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "total_value", "daily_return", "cashflow"])
        writer.writerow(["2024-01-01", 100000.0, 0.0, 100000.0])
        writer.writerow(["2024-01-02", 100000.0, 0.0, 90000.0])
        writer.writerow(["2024-01-03", 100000.0, 0.0, 95000.0])

    metrics = enrich_behavior_metrics(
        {
            "avg_cash_ratio": 0.0,
            "avg_gross_exposure": 0.0,
        },
        report_dir,
    )

    assert metrics["avg_cash_ratio"] == 0.95
    assert metrics["avg_gross_exposure"] == 0.05


def test_parallel_personality_results_preserve_behavior_metrics():
    generator = SimpleNamespace(
        start_date="2024-01-01",
        end_date="2024-01-05",
        tickers=["AAA"],
        market="us",
        initial_cash=100000.0,
    )

    results = MultiPersonalityComparisonReporterMixin.MultiPersonalityBacktest._build_personality_results_from_parallel(  # type: ignore[attr-defined]
        generator,
        [
            {
                "personality": "fundamental_value",
                "run_id": "mp_demo",
                "total_return": 1.0,
                "max_drawdown": 2.0,
                "sharpe_ratio": 0.5,
                "trade_count": 3,
                "win_rate": 0.5,
                "avg_position_days": 4.0,
                "metrics": {
                    "total_return": 1.0,
                    "max_drawdown": 2.0,
                    "sharpe_ratio": 0.5,
                    "total_trades": 3,
                    "win_rate": 0.5,
                    "avg_position_days": 4.0,
                    "avg_turnover_ratio": 0.12,
                    "avg_cash_ratio": 0.33,
                    "avg_gross_exposure": 0.67,
                },
                "token_usage": {},
                "error_count": 0,
                "duration_seconds": 1.0,
            }
        ],
    )

    metrics = results["fundamental_value"].result.metrics
    assert metrics["avg_turnover_ratio"] == 0.12
    assert metrics["avg_cash_ratio"] == 0.33
    assert metrics["avg_gross_exposure"] == 0.67
