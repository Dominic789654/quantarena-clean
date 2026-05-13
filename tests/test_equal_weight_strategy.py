"""Tests for strict equal-weight behavior in backtest engine."""

from typing import Dict

from backtest.engine import BacktestEngine


class _DummyTracker:
    def __init__(self) -> None:
        self.trades = []

    def record_trade(self, **kwargs) -> None:
        self.trades.append(kwargs)


def _make_engine_stub(
    personality: str = "ewi",
    cashflow: float = 1000.0,
    positions: Dict[str, Dict[str, float]] | None = None,
) -> BacktestEngine:
    tickers = ["AAA", "BBB"]
    engine = BacktestEngine.__new__(BacktestEngine)
    engine.tickers = tickers
    engine.personality = personality
    engine.use_llm = False
    engine.workflow_adapter = None
    engine.current_portfolio = {
        "cashflow": cashflow,
        "positions": positions
        if positions is not None
        else {ticker: {"shares": 0, "value": 0.0} for ticker in tickers},
    }
    engine.tracker = _DummyTracker()
    return engine


def test_equal_weight_aliases_detected() -> None:
    for name in ["ewi", "equal_weight", "equal_weight_index"]:
        engine = _make_engine_stub(personality=name)
        assert engine._is_equal_weight_personality()

    assert not _make_engine_stub(personality="balanced")._is_equal_weight_personality()


def test_initial_equal_weight_allocation_without_llm() -> None:
    engine = _make_engine_stub(personality="ewi", cashflow=1000.0)
    decisions = engine._generate_decisions("2025-11-04", {"AAA": 10.0, "BBB": 10.0})

    assert decisions["AAA"]["action"] == "BUY"
    assert decisions["BBB"]["action"] == "BUY"
    assert decisions["AAA"]["shares"] == 50
    assert decisions["BBB"]["shares"] == 50
    assert engine.current_portfolio["positions"]["AAA"]["shares"] == 50
    assert engine.current_portfolio["positions"]["BBB"]["shares"] == 50
    assert engine.current_portfolio["cashflow"] == 0.0
    assert len(engine.tracker.trades) == 2


def test_outside_rebalance_window_holds_positions() -> None:
    engine = _make_engine_stub(
        personality="equal_weight_index",
        cashflow=0.0,
        positions={
            "AAA": {"shares": 60, "value": 600.0},
            "BBB": {"shares": 40, "value": 400.0},
        },
    )
    decisions = engine._generate_decisions("2025-11-10", {"AAA": 10.0, "BBB": 10.0})

    assert decisions["AAA"]["action"] == "HOLD"
    assert decisions["BBB"]["action"] == "HOLD"
    assert engine.current_portfolio["positions"]["AAA"]["shares"] == 60
    assert engine.current_portfolio["positions"]["BBB"]["shares"] == 40
    assert len(engine.tracker.trades) == 0


def test_rebalance_window_executes_sell_then_buy() -> None:
    engine = _make_engine_stub(
        personality="equal_weight",
        cashflow=0.0,
        positions={
            "AAA": {"shares": 100, "value": 1000.0},
            "BBB": {"shares": 0, "value": 0.0},
        },
    )
    decisions = engine._generate_decisions("2025-06-03", {"AAA": 10.0, "BBB": 10.0})

    assert decisions["AAA"]["action"] == "SELL"
    assert decisions["AAA"]["shares"] == 50
    assert decisions["BBB"]["action"] == "BUY"
    assert decisions["BBB"]["shares"] == 50
    assert engine.current_portfolio["positions"]["AAA"]["shares"] == 50
    assert engine.current_portfolio["positions"]["BBB"]["shares"] == 50
    assert engine.current_portfolio["cashflow"] == 0.0
    assert len(engine.tracker.trades) == 2
