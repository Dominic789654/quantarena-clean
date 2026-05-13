"""Tests for unified behavior metrics helpers."""

from backtest.behavior_metrics import compute_behavior_metrics
from backtest.portfolio_tracker import PortfolioTracker


def test_compute_behavior_metrics_uses_tracker_snapshots():
    tracker = PortfolioTracker(initial_cash=100000.0, tickers=["AAA"])
    tracker.record_snapshot(
        "2024-01-01",
        40000.0,
        positions={"AAA": {"shares": 100, "value": 60000.0}},
        prices={"AAA": 600.0},
    )
    tracker.record_snapshot(
        "2024-01-02",
        50000.0,
        positions={"AAA": {"shares": 50, "value": 50000.0}},
        prices={"AAA": 1000.0},
    )

    metrics = compute_behavior_metrics(tracker, {})
    assert metrics["avg_cash_ratio"] == 0.45
    assert metrics["avg_gross_exposure"] == 0.55


def test_compute_behavior_metrics_merges_strategy_specific_fields():
    tracker = PortfolioTracker(initial_cash=100000.0, tickers=["AAA"])
    metrics = compute_behavior_metrics(
        tracker,
        {
            "avg_turnover_ratio": 0.12,
            "peak_turnover_ratio": 0.35,
            "value_consistency_score": 0.8,
            "crash_breaker_trigger_count": 2.0,
        },
    )
    assert metrics["avg_turnover_ratio"] == 0.12
    assert metrics["peak_turnover_ratio"] == 0.35
    assert metrics["value_consistency_score"] == 0.8
    assert metrics["crash_breaker_trigger_count"] == 2.0
