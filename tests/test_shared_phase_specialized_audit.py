"""Regression tests for shared-phase personality execution and audit coverage."""

from pathlib import Path
from types import SimpleNamespace

from backtest.behavioral_momentum_engine import BehavioralMomentumBacktestEngine
from backtest.engine import BacktestEngine
from backtest.fundamental_value_engine import FundamentalValueBacktestEngine
from backtest.workflow_adapter import BacktestDecision


class CollectSignalsForbidden:
    def collect_signals_only(self, *args, **kwargs):
        raise AssertionError("shared-phase specialized path must not recompute analyst signals")

    def close(self):
        return None


class StaticAllocator:
    def __init__(self, weights):
        self.weights = weights
        self.calls = []

    def allocate(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.weights)


class SmartPriorityWorkflow:
    def run_single_day_with_precollected_signals(
        self,
        trading_date,
        prices,
        enhanced_signals,
        priority_order=None,
        prev_portfolio=None,
    ):
        return {
            "AAA": BacktestDecision(
                ticker="AAA",
                action="BUY",
                shares=2,
                price=prices["AAA"],
                justification="shared smart priority buy",
                analyst_signals={},
            )
        }

    def close(self):
        return None


def _enable_portfolio_mode(engine, allocator):
    engine.portfolio_mode = True
    engine.smart_priority_mode = True
    engine.workflow_adapter = CollectSignalsForbidden()
    engine.portfolio_allocator = allocator


def test_fundamental_value_shared_phase_applies_filter_without_recollecting(monkeypatch, tmp_path: Path):
    engine = FundamentalValueBacktestEngine(
        tickers=["AAA", "BBB"],
        start_date="2026-01-01",
        end_date="2026-01-02",
        initial_cash=1000.0,
        db_path=str(tmp_path / "value.db"),
        use_llm=False,
        personality="fundamental_value",
    )
    allocator = StaticAllocator({"AAA": 0.5})
    _enable_portfolio_mode(engine, allocator)

    fundamentals = {
        "AAA": SimpleNamespace(
            ev_to_ebitda=10.0,
            return_on_assets_ttm=0.1,
            operating_cash_flow=100.0,
            current_ratio=2.0,
        ),
        "BBB": SimpleNamespace(
            ev_to_ebitda=25.0,
            return_on_assets_ttm=0.1,
            operating_cash_flow=100.0,
            current_ratio=2.0,
        ),
    }
    monkeypatch.setattr(engine, "_get_fundamentals", lambda ticker: fundamentals[ticker])

    try:
        decisions = engine._generate_llm_decisions_with_precollected_signals(
            "2026-01-02",
            {"AAA": 10.0, "BBB": 20.0},
            {
                "AAA": {"summary": {"bullish_count": 1, "bearish_count": 0}},
                "BBB": {"summary": {"bullish_count": 1, "bearish_count": 0}},
            },
            priority_order=["AAA", "BBB"],
        )

        assert allocator.calls
        assert set(allocator.calls[0]["signals"]) == {"AAA"}
        assert decisions["AAA"]["action"] == "BUY"
        assert decisions["AAA"]["_applied"] is True
        assert decisions["BBB"]["action"] == "HOLD"
        assert engine._value_behavior_metrics()["value_filter_pass_rate"] == 50.0
        assert len(engine.tracker.trades) == 1
        assert len(engine.broker_audit_events) == 1
    finally:
        engine.close()


def test_behavioral_momentum_shared_phase_applies_controls_without_recollecting(monkeypatch, tmp_path: Path):
    engine = BehavioralMomentumBacktestEngine(
        tickers=["AAA", "BBB"],
        start_date="2026-01-01",
        end_date="2026-01-02",
        initial_cash=1000.0,
        db_path=str(tmp_path / "momentum.db"),
        use_llm=False,
        personality="behavioral_momentum",
    )
    allocator = StaticAllocator({"AAA": 0.8, "BBB": 0.2})
    _enable_portfolio_mode(engine, allocator)
    monkeypatch.setattr(engine, "_market_crash_breaker_multiplier", lambda date: 1.0)
    monkeypatch.setattr(engine, "_compute_vol_scaling", lambda ticker, date: 0.5 if ticker == "AAA" else 1.0)

    try:
        decisions = engine._generate_llm_decisions_with_precollected_signals(
            "2026-01-02",
            {"AAA": 10.0, "BBB": 20.0},
            {
                "AAA": {"summary": {"bullish_count": 3, "bearish_count": 1}},
                "BBB": {"summary": {"bullish_count": 1, "bearish_count": 3}},
            },
            priority_order=["AAA", "BBB"],
        )

        assert allocator.calls
        assert decisions["AAA"]["action"] == "BUY"
        assert decisions["AAA"]["shares"] == 30
        assert decisions["BBB"]["action"] == "BUY"
        assert decisions["BBB"]["shares"] == 2
        metrics = engine._momentum_behavior_metrics()
        assert metrics["vol_scaling_activation_rate"] == 1.0
        assert metrics["avg_momentum_exposure_multiplier"] == 1.0
        assert len(engine.tracker.trades) == 2
        assert len(engine.broker_audit_events) == 2
    finally:
        engine.close()


def test_shared_smart_priority_decisions_route_through_paper_broker_audit(tmp_path: Path):
    engine = BacktestEngine(
        tickers=["AAA"],
        start_date="2026-01-01",
        end_date="2026-01-02",
        initial_cash=1000.0,
        db_path=str(tmp_path / "smart.db"),
        use_llm=False,
        personality="balanced",
    )
    engine.use_llm = True
    engine.smart_priority_mode = True
    engine.workflow_adapter = SmartPriorityWorkflow()

    try:
        decisions = engine._generate_llm_decisions_with_precollected_signals(
            "2026-01-02",
            {"AAA": 10.0},
            {"AAA": {"summary": {"bullish_count": 1, "bearish_count": 0}}},
            priority_order=["AAA"],
        )
        assert decisions["AAA"]["_applied"] is False

        engine._execute_day_with_decisions("2026-01-02", {"AAA": 10.0}, decisions)

        assert engine.current_portfolio["cashflow"] == 980.0
        assert engine.current_portfolio["positions"]["AAA"]["shares"] == 2
        assert len(engine.tracker.trades) == 1
        assert len(engine.broker_audit_events) == 1
        event = engine.broker_audit_events[0]
        assert event["outcome"] == "filled"
        assert event["source_justification"] == "shared smart priority buy"
    finally:
        engine.close()
