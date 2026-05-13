"""Tests for benchmark-aware metrics and reporting outputs."""

from types import SimpleNamespace
import json

import pandas as pd
import numpy as np

from backtest.engine import BacktestEngine
from backtest.metrics import PerformanceMetrics
from backtest.portfolio_tracker import PortfolioTracker
from backtest.report import ReportGenerator


def _build_tracker() -> PortfolioTracker:
    tracker = PortfolioTracker(initial_cash=100000.0, tickers=["AAA"])
    tracker.record_snapshot("2025-01-02", 100000.0, {}, {})
    tracker.record_snapshot("2025-01-03", 101000.0, {}, {})
    tracker.record_snapshot("2025-01-06", 100500.0, {}, {})
    return tracker


def test_calculate_all_includes_benchmark_metrics() -> None:
    tracker = _build_tracker()
    benchmark_returns = pd.Series(
        [0.0, 0.4, -0.2],
        index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
    )

    metrics = PerformanceMetrics.calculate_all(
        tracker,
        final_prices={"AAA": 10.0},
        benchmark_returns=benchmark_returns,
    )

    assert "excess_return" in metrics
    assert "alpha" in metrics
    assert "beta" in metrics
    assert "tracking_error" in metrics
    assert "information_ratio" in metrics
    assert "benchmark_annualized_return" in metrics


def test_calculate_all_computes_non_default_benchmark_metrics() -> None:
    """Regression: benchmark metrics should not fall back to default placeholders."""
    tracker = _build_tracker()
    benchmark_returns = pd.Series(
        [0.0, 0.4, -0.2],
        index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
    )

    metrics = PerformanceMetrics.calculate_all(
        tracker,
        final_prices={"AAA": 10.0},
        benchmark_returns=benchmark_returns,
    )

    # These values were previously defaulted when portfolio/benchmark indexes
    # failed to align (portfolio index as RangeIndex vs benchmark DatetimeIndex).
    assert metrics["benchmark_annualized_return"] != 0.0
    assert metrics["excess_return"] != 0.0
    assert metrics["tracking_error"] > 0.0


def test_equity_curve_csv_contains_benchmark_columns(tmp_path) -> None:
    tracker = _build_tracker()
    benchmark_curve = pd.Series(
        [100000.0, 100400.0, 100200.0],
        index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
        name="benchmark_value",
    )
    result = SimpleNamespace(
        tracker=tracker,
        benchmark_curve=benchmark_curve,
        benchmark_source="index:000300.SH",
    )

    report = ReportGenerator(output_dir=str(tmp_path))
    csv_text = report.generate_equity_curve_csv(result, str(tmp_path / "equity_curve.csv"))
    df = pd.read_csv(pd.io.common.StringIO(csv_text))

    assert "benchmark_value" in df.columns
    assert "benchmark_return" in df.columns
    assert abs(df["benchmark_return"].iloc[-1] - 0.2) < 1e-6


def test_us_index_benchmark_curve_uses_real_index_when_available(monkeypatch) -> None:
    engine = BacktestEngine.__new__(BacktestEngine)
    engine.initial_cash = 100000.0

    fake_df = pd.DataFrame(
        {
            "Adj Close": [100.0, 101.0, 102.0],
            "Close": [99.0, 100.0, 101.0],
        },
        index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
    )

    class _YF:
        @staticmethod
        def download(symbol, start, end, progress, auto_adjust):
            assert symbol == "SPY"
            return fake_df

    monkeypatch.setattr("importlib.import_module", lambda name: _YF())

    curve = BacktestEngine._build_us_index_benchmark_curve(
        engine,
        ["2025-01-02", "2025-01-03", "2025-01-06"],
        "SPY",
    )

    assert list(curve.index.strftime("%Y-%m-%d")) == ["2025-01-02", "2025-01-03", "2025-01-06"]
    assert curve.iloc[0] == 100000.0
    assert curve.iloc[-1] == 102000.0


def test_us_index_benchmark_curve_rejects_leading_gaps(monkeypatch) -> None:
    engine = BacktestEngine.__new__(BacktestEngine)
    engine.initial_cash = 100000.0

    fake_df = pd.DataFrame(
        {
            "Close": [101.0, 102.0],
        },
        index=pd.to_datetime(["2025-01-03", "2025-01-06"]),
    )

    class _YF:
        @staticmethod
        def download(symbol, start, end, progress, auto_adjust):
            return fake_df

    monkeypatch.setattr("importlib.import_module", lambda name: _YF())

    curve = BacktestEngine._build_us_index_benchmark_curve(
        engine,
        ["2025-01-02", "2025-01-03", "2025-01-06"],
        "SPY",
    )

    assert curve.empty


def test_us_index_benchmark_curve_supports_yfinance_multiindex(monkeypatch) -> None:
    engine = BacktestEngine.__new__(BacktestEngine)
    engine.initial_cash = 100000.0

    fake_df = pd.DataFrame(
        {
            ("Close", "SPY"): [100.0, 101.0, 102.0],
        },
        index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
    )

    class _YF:
        @staticmethod
        def download(symbol, start, end, progress, auto_adjust):
            return fake_df

    monkeypatch.setattr("importlib.import_module", lambda name: _YF())

    curve = BacktestEngine._build_us_index_benchmark_curve(
        engine,
        ["2025-01-02", "2025-01-03", "2025-01-06"],
        "SPY",
    )

    assert curve.iloc[0] == 100000.0
    assert curve.iloc[-1] == 102000.0


def test_metrics_json_sanitizes_infinite_calmar(tmp_path) -> None:
    tracker = PortfolioTracker(initial_cash=100000.0, tickers=["AAA"])
    tracker.record_snapshot("2025-01-02", 100000.0, {}, {})
    tracker.record_snapshot("2025-01-03", 101000.0, {}, {})
    result = SimpleNamespace(
        run_id="json-demo",
        start_date="2025-01-02",
        end_date="2025-01-03",
        market="us",
        tickers=["AAA"],
        initial_cash=100000.0,
        tracker=tracker,
        metrics={"calmar_ratio": float("inf")},
        config={},
    )

    report = ReportGenerator(output_dir=str(tmp_path))
    json_text = report.generate_metrics_json(result)
    payload = json.loads(json_text)

    assert payload["metrics"]["calmar_ratio"] is None


def test_summary_omits_benchmark_return_when_unavailable(tmp_path) -> None:
    tracker = _build_tracker()
    result = SimpleNamespace(
        run_id="summary-demo",
        start_date="2025-01-02",
        end_date="2025-01-06",
        market="us",
        tickers=["AAA"],
        initial_cash=100000.0,
        tracker=tracker,
        config={},
        metrics={
            "initial_cash": 100000.0,
            "final_value": 100500.0,
            "total_return": 0.5,
            "annualized_return": 1.0,
            "trading_days": 3,
            "benchmark_total_return": 0.0,
            "benchmark_source": "none",
        },
        errors=[],
    )

    report = ReportGenerator(output_dir=str(tmp_path)).generate_markdown(result)
    assert "Benchmark Source" in report
    assert "Benchmark Return" not in report


def test_metrics_json_sanitizes_numpy_scalars(tmp_path) -> None:
    tracker = PortfolioTracker(initial_cash=100000.0, tickers=["AAA"])
    tracker.record_snapshot("2025-01-02", 100000.0, {}, {})
    result = SimpleNamespace(
        run_id="json-numpy",
        start_date="2025-01-02",
        end_date="2025-01-02",
        market="us",
        tickers=["AAA"],
        initial_cash=100000.0,
        tracker=tracker,
        metrics={"tracking_error": np.float64(1.23), "stamp": pd.Timestamp("2025-01-02")},
        config={},
    )

    report = ReportGenerator(output_dir=str(tmp_path))
    json_text = report.generate_metrics_json(result)
    payload = json.loads(json_text)

    assert payload["metrics"]["tracking_error"] == 1.23
    assert payload["metrics"]["stamp"].startswith("2025-01-02")
