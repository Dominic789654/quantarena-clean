"""Regression tests for the metric semantics used in QuantArena results.

These checks intentionally use a tiny deterministic portfolio so future
refactors cannot silently change the return, risk, turnover, or behavior
definitions that paper tables and release artifacts depend on.
"""

import pytest

from backtest.behavior_metrics import compute_behavior_metrics
from backtest.metrics import PerformanceMetrics
from backtest.portfolio_tracker import PortfolioTracker


def _golden_tracker() -> PortfolioTracker:
    tracker = PortfolioTracker(initial_cash=100_000.0, tickers=["AAA"])

    tracker.record_trade(date="2026-01-02", ticker="AAA", action="BUY", shares=100, price=100.0)
    tracker.record_trade(date="2026-01-03", ticker="AAA", action="BUY", shares=100, price=110.0)
    tracker.record_trade(date="2026-01-06", ticker="AAA", action="SELL", shares=50, price=120.0)

    tracker.record_snapshot(
        "2026-01-02",
        80_000.0,
        {"AAA": {"shares": 200, "value": 20_000.0}},
        {"AAA": 100.0},
    )
    tracker.record_snapshot(
        "2026-01-03",
        79_000.0,
        {"AAA": {"shares": 200, "value": 24_000.0}},
        {"AAA": 120.0},
    )
    tracker.record_snapshot(
        "2026-01-06",
        82_000.0,
        {"AAA": {"shares": 200, "value": 16_000.0}},
        {"AAA": 80.0},
    )
    tracker.record_snapshot(
        "2026-01-07",
        86_000.0,
        {"AAA": {"shares": 200, "value": 20_000.0}},
        {"AAA": 100.0},
    )

    return tracker


def test_golden_performance_metrics_preserve_paper_units_and_rounding():
    tracker = _golden_tracker()

    metrics = PerformanceMetrics.calculate_all(tracker)

    assert metrics["total_return"] == 6.0
    assert metrics["annualized_return"] == 3828.89
    assert metrics["max_drawdown"] == 4.85
    assert metrics["max_drawdown_duration"] == 1
    assert metrics["volatility"] == 86.59
    assert metrics["sharpe_ratio"] == 4.57
    assert metrics["sortino_ratio"] == 7.26
    assert metrics["calmar_ratio"] == 789.46
    assert metrics["cvar_95"] == 4.85
    assert metrics["trading_days"] == 4
    assert metrics["total_trades"] == 3
    assert metrics["avg_position_days"] == 4.0
    assert metrics["initial_cash"] == 100_000.0
    assert metrics["final_value"] == 106_000.0
    assert metrics["final_cash"] == 86_000.0


def test_golden_behavior_metrics_preserve_cash_exposure_and_turnover_contract():
    tracker = _golden_tracker()

    turnover = PerformanceMetrics.turnover_stats(tracker)
    behavior = compute_behavior_metrics(tracker, turnover)

    assert turnover == {
        "avg_turnover_ratio": 0.0335,
        "peak_turnover_ratio": 0.055,
        "annualized_turnover_ratio": 8.45,
        "total_turnover_ratio": 0.1341,
    }
    assert behavior["avg_cash_ratio"] == 0.8038
    assert behavior["avg_gross_exposure"] == 0.1962
    assert behavior["avg_turnover_ratio"] == 0.0335
    assert behavior["peak_turnover_ratio"] == 0.055


def test_legacy_drawdown_contract_stays_negative_decimal():
    values = [100_000.0, 103_000.0, 98_000.0, 106_000.0]

    assert PerformanceMetrics.calculate_max_drawdown(values) == pytest.approx(-0.0485)
