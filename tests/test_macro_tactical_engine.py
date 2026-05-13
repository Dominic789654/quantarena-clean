"""Unit tests for the Macro Tactical backtest engine."""

import sys
import types
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest.macro_tactical_engine import MacroTacticalBacktestEngine
from backtest.providers import ReplayMacroProvider


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
        if self.personality == "conservative":
            return {"AAA": 0.10, "BBB": 0.05}
        if self.personality == "balanced":
            return {"AAA": 0.12, "BBB": 0.08}
        if self.personality == "aggressive":
            return {"AAA": 0.20, "BBB": 0.02}
        return {"AAA": 0.05, "BBB": 0.10}


@dataclass
class _StubPortfolio:
    cashflow: float
    positions: dict


def _install_stub_portfolio_allocator(monkeypatch):
    stub_module = types.ModuleType("backtest.portfolio_allocator")
    stub_module.PortfolioAllocator = _StubAllocator
    stub_module.Portfolio = _StubPortfolio
    monkeypatch.setitem(sys.modules, "backtest.portfolio_allocator", stub_module)


def _make_engine(monkeypatch, tmp_path: Path, **kwargs) -> MacroTacticalBacktestEngine:
    _install_stub_portfolio_allocator(monkeypatch)
    return MacroTacticalBacktestEngine(
        tickers=["AAA", "BBB"],
        start_date="2024-01-01",
        end_date="2024-03-31",
        db_path=str(tmp_path / "macro_tactical.db"),
        use_llm=False,
        personality="macro_tactical",
        config={
            "macro_tactical": {
                "short_window": 20,
                "crash_window": 5,
                "long_ma_window": 60,
                "bull_return_threshold": 0.03,
                "bear_return_threshold": -0.05,
                "volatile_rally_threshold": 0.04,
                "high_vol_threshold": 0.25,
                "inflation_hot_threshold": 3.5,
                "unemployment_bad_threshold": 6.0,
                "rate_tight_threshold": 4.5,
            },
            "fof": {"sleeves": ["conservative", "balanced", "aggressive", "passive"]},
        },
        **kwargs,
    )


def test_macro_tactical_regime_turns_volatile_on_sharp_rebound_below_ma(monkeypatch, tmp_path: Path):
    engine = _make_engine(monkeypatch, tmp_path)
    try:
        values = [120] * 55 + [90, 91, 92, 93, 94, 95]
        market_proxy = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))
        monkeypatch.setattr(engine, "_build_market_proxy_series", lambda date: market_proxy)
        regime = engine._derive_regime_from_market_proxy("2024-03-01", macro_bias=0)
        assert regime["regime"] == "volatile"
    finally:
        engine.close()


def test_macro_tactical_macro_bias_can_push_neutral_to_bear(monkeypatch, tmp_path: Path):
    engine = _make_engine(monkeypatch, tmp_path)
    try:
        values = [100 + (i * 0.05) for i in range(80)]
        market_proxy = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))
        monkeypatch.setattr(engine, "_build_market_proxy_series", lambda date: market_proxy)
        regime = engine._derive_regime_from_market_proxy("2024-03-20", macro_bias=-2)
        assert regime["regime"] == "bear"
    finally:
        engine.close()


def test_macro_tactical_build_market_context_merges_macro_overlay(monkeypatch, tmp_path: Path):
    engine = _make_engine(monkeypatch, tmp_path)
    try:
        monkeypatch.setattr(engine, "_fetch_macro_snapshot", lambda: {"cpi": 4.1, "unemployment": 6.5, "policy_rate": 5.0})
        monkeypatch.setattr(
            engine,
            "_derive_regime_from_market_proxy",
            lambda date, macro_bias=0: {
                "regime": "bear",
                "market_short_return": -0.03,
                "market_crash_return": 0.01,
                "market_volatility": 0.18,
            },
        )
        context = engine._build_market_context({"AAA": {"summary": {"bullish_count": 1, "bearish_count": 2}, "trading_date": "2024-03-20"}})
        assert context["regime"] == "bear"
        assert context["macro_bias"] <= -2
        assert context["macro_snapshot"]["cpi"] == 4.1
    finally:
        engine.close()


def test_macro_tactical_fetch_macro_snapshot_uses_injected_provider(monkeypatch, tmp_path: Path):
    provider = ReplayMacroProvider(
        {
            "cpi": {"value": "0.041"},
            "unemployment": {"value": "0.065"},
            "federal_funds_rate": {"value": "0.05"},
        }
    )
    engine = _make_engine(monkeypatch, tmp_path, market="us", macro_provider=provider)
    try:
        snapshot = engine._fetch_macro_snapshot()
        assert snapshot == pytest.approx({"cpi": 4.1, "unemployment": 6.5, "policy_rate": 5.0})
    finally:
        engine.close()


def test_macro_tactical_fetch_macro_snapshot_falls_back_when_injected_provider_fails(
    monkeypatch,
    tmp_path: Path,
):
    class FailingMacroProvider:
        name = "failing_macro"

        def get_economic_indicators(self, market):
            raise RuntimeError("macro provider unavailable")

    engine = _make_engine(monkeypatch, tmp_path, market="us", macro_provider=FailingMacroProvider())
    try:
        assert engine._fetch_macro_snapshot() == {
            "cpi": None,
            "unemployment": None,
            "policy_rate": None,
        }
    finally:
        engine.close()


def test_macro_tactical_fetch_macro_snapshot_default_path_uses_us_router(
    monkeypatch,
    tmp_path: Path,
):
    calls = []

    class FakeRouter:
        def __init__(self, source):
            calls.append(("init", source))

        def get_us_economic_indicators(self):
            calls.append(("us", None))
            return SimpleNamespace(
                cpi={"value": "4.1"},
                unemployment={"value": "6.5"},
                federal_funds_rate={"value": "5.0"},
            )

        def get_cn_economic_indicators(self):
            raise AssertionError("US market should not fetch CN indicators")

    monkeypatch.setattr("backtest.macro_tactical_engine.Router", FakeRouter)
    monkeypatch.setattr("backtest.macro_tactical_engine.resolve_api_source", lambda market, cfg: "fmp")

    engine = _make_engine(monkeypatch, tmp_path, market="us")
    try:
        snapshot = engine._fetch_macro_snapshot()
        assert snapshot == {"cpi": 4.1, "unemployment": 6.5, "policy_rate": 5.0}
        assert calls == [("init", "fmp"), ("us", None)]
    finally:
        engine.close()


def test_macro_tactical_fetch_macro_snapshot_default_path_uses_cn_router(
    monkeypatch,
    tmp_path: Path,
):
    calls = []

    class FakeRouter:
        def __init__(self, source):
            calls.append(("init", source))

        def get_cn_economic_indicators(self):
            calls.append(("cn", None))
            return SimpleNamespace(cpi={"value": "3.8"}, unemployment_rate={"value": "5.4"}, loan_rate={"value": "3.45"})

        def get_us_economic_indicators(self):
            raise AssertionError("CN market should not fetch US indicators")

    monkeypatch.setattr("backtest.macro_tactical_engine.Router", FakeRouter)
    monkeypatch.setattr("backtest.macro_tactical_engine.resolve_api_source", lambda market, cfg: "tushare")

    engine = _make_engine(monkeypatch, tmp_path, market="cn")
    try:
        snapshot = engine._fetch_macro_snapshot()
        assert snapshot == {"cpi": 3.8, "unemployment": 5.4, "policy_rate": 3.45}
        assert calls == [("init", "tushare"), ("cn", None)]
    finally:
        engine.close()
