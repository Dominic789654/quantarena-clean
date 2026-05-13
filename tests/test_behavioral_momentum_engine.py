"""Unit tests for the Behavioral Momentum backtest engine."""

from pathlib import Path

import pandas as pd

from backtest.behavioral_momentum_engine import BehavioralMomentumBacktestEngine


def _make_engine(tmp_path: Path) -> BehavioralMomentumBacktestEngine:
    return BehavioralMomentumBacktestEngine(
        tickers=["AAA", "BBB"],
        start_date="2024-01-01",
        end_date="2024-03-31",
        db_path=str(tmp_path / "behavioral_momentum.db"),
        use_llm=False,
        personality="behavioral_momentum",
        config={
            "momentum": {
                "target_vol": 0.15,
                "vol_window": 21,
                "market_ma_window": 60,
                "crash_lookback_days": 5,
                "crash_return_threshold": 0.04,
                "crash_exposure_multiplier": 0.2,
                "max_scaling": 1.5,
                "min_scaling": 0.2,
            }
        },
    )


def test_compute_vol_scaling_caps_to_max_scaling(monkeypatch, tmp_path: Path):
    engine = _make_engine(tmp_path)
    try:
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        low_vol_prices = pd.Series([100 + i * 0.01 for i in range(30)], index=dates)
        monkeypatch.setattr(engine, "_load_price_series", lambda ticker, date, lookback_days: low_vol_prices)
        scaling = engine._compute_vol_scaling("AAA", "2024-01-30")
        assert scaling == 1.5
    finally:
        engine.close()


def test_market_crash_breaker_triggers_when_short_rally_happens_below_ma(monkeypatch, tmp_path: Path):
    engine = _make_engine(tmp_path)
    try:
        values = [120] * 55 + [90, 91, 92, 93, 94, 95]
        market_proxy = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))
        monkeypatch.setattr(engine, "_build_market_proxy_series", lambda date: market_proxy)
        multiplier = engine._market_crash_breaker_multiplier("2024-03-01")
        assert multiplier == 0.2
        assert engine._crash_breaker_trigger_count == 1
    finally:
        engine.close()


def test_market_crash_breaker_not_triggered_without_signal(monkeypatch, tmp_path: Path):
    engine = _make_engine(tmp_path)
    try:
        values = [100 + i for i in range(70)]
        market_proxy = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))
        monkeypatch.setattr(engine, "_build_market_proxy_series", lambda date: market_proxy)
        multiplier = engine._market_crash_breaker_multiplier("2024-03-10")
        assert multiplier == 1.0
        assert engine._crash_breaker_trigger_count == 0
    finally:
        engine.close()


def test_momentum_behavior_metrics_use_internal_counters(tmp_path: Path):
    engine = _make_engine(tmp_path)
    try:
        engine._vol_scaling_events = 3
        engine._crash_breaker_trigger_count = 2
        engine._exposure_multipliers = [1.0, 0.2, 1.0]
        engine._momentum_days = 3
        metrics = engine._momentum_behavior_metrics()
        assert metrics["vol_scaling_activation_rate"] == 1.0
        assert metrics["crash_breaker_trigger_count"] == 2.0
        assert metrics["avg_momentum_exposure_multiplier"] == 0.7333
    finally:
        engine.close()
