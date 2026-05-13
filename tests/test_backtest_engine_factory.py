"""Tests for backtest engine factory routing with scaffolded paradigms."""

import sys
import types
from dataclasses import dataclass
from pathlib import Path

from backtest.behavioral_momentum_engine import BehavioralMomentumBacktestEngine
from backtest.engine import BacktestEngine, create_backtest_engine, _resolve_backtest_engine_route
from backtest.fof_engine import FOFBacktestEngine
from backtest.fundamental_value_engine import FundamentalValueBacktestEngine
from backtest.macro_tactical_engine import MacroTacticalBacktestEngine
from backtest.smart_beta_engine import SmartBetaBacktestEngine


class _StubAllocator:
    PERSONALITY_ALIASES = {
        "conservative": "conservative",
        "balanced": "balanced",
        "aggressive": "aggressive",
        "passive": "passive",
        "equal_weight_index": "equal_weight_index",
        "equal_weight": "equal_weight_index",
        "ewi": "equal_weight_index",
        "fof": "fof",
        "macro_tactical": "macro_tactical",
        "tactical_allocation": "macro_tactical",
    }

    def __init__(self, personality: str = "balanced"):
        self.personality = self.PERSONALITY_ALIASES.get(personality, personality)

    def allocate(self, signals, current_portfolio, prices, trading_date, decision_memory=None):
        return {"AAA": 0.1}


@dataclass
class _StubPortfolio:
    cashflow: float
    positions: dict


def _install_stub_portfolio_allocator(monkeypatch):
    stub_module = types.ModuleType("backtest.portfolio_allocator")
    stub_module.PortfolioAllocator = _StubAllocator
    stub_module.Portfolio = _StubPortfolio
    monkeypatch.setitem(sys.modules, "backtest.portfolio_allocator", stub_module)


def test_create_backtest_engine_returns_value_engine_for_fundamental_value(tmp_path: Path):
    engine = create_backtest_engine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        db_path=str(tmp_path / "fundamental_value.db"),
        personality="fundamental_value",
        use_llm=False,
    )
    try:
        assert isinstance(engine, FundamentalValueBacktestEngine)
        assert engine.personality == "fundamental_value"
    finally:
        engine.close()


def test_create_backtest_engine_returns_momentum_engine_for_behavioral_momentum_alias(tmp_path: Path):
    engine = create_backtest_engine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        db_path=str(tmp_path / "behavioral_momentum.db"),
        personality="momentum",
        use_llm=False,
    )
    try:
        assert isinstance(engine, BehavioralMomentumBacktestEngine)
        assert engine.personality == "momentum"
    finally:
        engine.close()


def test_create_backtest_engine_returns_macro_tactical_engine_for_alias(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)
    engine = create_backtest_engine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        db_path=str(tmp_path / "macro_tactical.db"),
        personality="tactical_allocation",
        use_llm=False,
    )
    try:
        assert isinstance(engine, MacroTacticalBacktestEngine)
        assert engine.personality == "macro_tactical"
    finally:
        engine.close()


def test_engine_factory_route_table_covers_profile_aliases():
    """Factory routing keeps legacy alias values unless an engine already canonicalizes them."""
    cases = [
        ("balanced", BacktestEngine, "balanced"),
        ("fof", FOFBacktestEngine, "fof"),
        ("macro_tactical", MacroTacticalBacktestEngine, "macro_tactical"),
        ("tactical_allocation", MacroTacticalBacktestEngine, "macro_tactical"),
        ("fundamental_value", FundamentalValueBacktestEngine, "fundamental_value"),
        ("value", FundamentalValueBacktestEngine, "value"),
        ("behavioral_momentum", BehavioralMomentumBacktestEngine, "behavioral_momentum"),
        ("momentum", BehavioralMomentumBacktestEngine, "momentum"),
        ("smart_beta_passive", SmartBetaBacktestEngine, "smart_beta_passive"),
        ("smart_beta", SmartBetaBacktestEngine, "smart_beta"),
    ]

    for raw_personality, expected_engine_cls, expected_personality in cases:
        engine_cls, routed_personality = _resolve_backtest_engine_route(raw_personality)
        assert engine_cls is expected_engine_cls
        assert routed_personality == expected_personality
