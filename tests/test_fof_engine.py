import pytest
import sys
import types
from dataclasses import dataclass
from pathlib import Path

from backtest.engine import create_backtest_engine
from backtest.fof_engine import FOFBacktestEngine


class _FakeWorkflowAdapter:
    def collect_signals_only_parallel_v2(self, trading_date: str, prices):
        return {
            "AAA": {
                "summary": {
                    "bullish_count": 3,
                    "bearish_count": 0,
                    "neutral_count": 1,
                    "avg_confidence": 0.8,
                    "signal_consistency": 0.9,
                }
            },
            "BBB": {
                "summary": {
                    "bullish_count": 0,
                    "bearish_count": 2,
                    "neutral_count": 2,
                    "avg_confidence": 0.6,
                    "signal_consistency": 0.7,
                }
            },
        }

    def close(self):
        return None


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


def test_create_backtest_engine_returns_fof_engine(monkeypatch):
    import backtest.engine as engine_module

    _install_stub_portfolio_allocator(monkeypatch)
    monkeypatch.setattr(engine_module, "create_workflow_adapter", lambda **_: _FakeWorkflowAdapter())

    engine = create_backtest_engine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        personality="fof",
    )
    try:
        assert isinstance(engine, FOFBacktestEngine)
    finally:
        engine.close()


def test_fof_engine_normalizes_and_deduplicates_sleeves(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)

    engine = FOFBacktestEngine(
        tickers=["AAA", "BBB"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        initial_cash=100000.0,
        market="cn",
        db_path=str(tmp_path / "fof_norm.db"),
        use_llm=False,
        config={"fof": {"sleeves": ["balanced", "equal_weight", "ewi", "passive"]}},
    )
    try:
        assert engine.fof_sleeves == ["balanced", "equal_weight_index", "passive"]
        assert list(engine.sleeve_allocators.keys()) == ["balanced", "equal_weight_index", "passive"]
        assert engine.config["fof"]["sleeves"] == ["balanced", "equal_weight_index", "passive"]
    finally:
        engine.close()


def test_fof_engine_supports_configured_sleeve_objects(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)

    engine = FOFBacktestEngine(
        tickers=["AAA", "BBB"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        initial_cash=100000.0,
        market="cn",
        db_path=str(tmp_path / "fof_cfg.db"),
        use_llm=False,
        config={
            "fof": {
                "sleeves": [
                    {"personality": "balanced", "weight": 0.55},
                    {"name": "equal_weight", "base_weight": 0.25},
                    {"personality": "passive", "enabled": False},
                    {"personality": "aggressive", "weight": 0.20},
                ]
            }
        },
    )
    try:
        assert engine.fof_sleeves == ["balanced", "equal_weight_index", "aggressive"]
        assert engine.config["fof"]["base_weights"]["balanced"] == 0.55
        assert engine.config["fof"]["base_weights"]["equal_weight_index"] == 0.25
        assert engine.config["fof"]["base_weights"]["aggressive"] == 0.20
        assert engine.config["fof"]["sleeve_configs"] == [
            {"personality": "balanced", "base_weight": 0.55},
            {"personality": "equal_weight_index", "base_weight": 0.25},
            {"personality": "aggressive", "base_weight": 0.20},
        ]
    finally:
        engine.close()


def test_fof_engine_initializes_workflow_with_fof_personality(monkeypatch):
    import backtest.engine as engine_module

    captured = {}

    _install_stub_portfolio_allocator(monkeypatch)

    def _fake_create_workflow_adapter(**kwargs):
        captured.update(kwargs)
        return _FakeWorkflowAdapter()

    monkeypatch.setattr(engine_module, "create_workflow_adapter", _fake_create_workflow_adapter)

    engine = create_backtest_engine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        personality="fof",
        use_llm=True,
        analysts=["fundamental"],
    )
    try:
        assert isinstance(engine, FOFBacktestEngine)
        assert captured["personality"] == "fof"
    finally:
        engine.close()


def test_fof_engine_generates_meta_allocated_decisions(monkeypatch, tmp_path: Path):
    import backtest.engine as engine_module

    _install_stub_portfolio_allocator(monkeypatch)
    monkeypatch.setattr(engine_module, "create_workflow_adapter", lambda **_: _FakeWorkflowAdapter())

    engine = FOFBacktestEngine(
        tickers=["AAA", "BBB"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        initial_cash=100000.0,
        market="cn",
        db_path=str(tmp_path / "fof.db"),
        use_llm=True,
        analysts=["fundamental"],
        config={"fof": {"sleeves": ["conservative", "balanced", "aggressive", "passive"]}},
    )
    try:
        decisions = engine._generate_decisions("2024-01-02", {"AAA": 10.0, "BBB": 20.0})
        assert set(decisions) == {"AAA", "BBB"}
        assert any(decision["action"] == "BUY" for decision in decisions.values())
        assert all("FOF target" in decision["justification"] for decision in decisions.values())
        assert engine.last_fof_allocation is not None
        assert abs(sum(engine.last_fof_allocation.sleeve_weights.values()) - 1.0) < 1e-9
        assert engine.fof_daily_allocations[-1]["sleeve_returns"]["balanced"] == 0.0
        assert "sleeve_target_weights" in engine.fof_daily_allocations[-1]
        assert "balanced" in engine.fof_daily_allocations[-1]["sleeve_target_weights"]
        assert "sleeve_consensus" in engine.fof_daily_allocations[-1]
        assert engine.fof_daily_allocations[-1]["sleeve_consensus"]["top_tickers"][0]["support_count"] >= 1
        assert "rebalance_stats" in engine.fof_daily_allocations[-1]
        assert engine.fof_daily_allocations[-1]["rebalance_stats"]["executed_trades"] >= 1
    finally:
        engine.close()


def test_fof_engine_skips_small_rebalance_below_threshold(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)

    engine = FOFBacktestEngine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        initial_cash=0.0,
        market="cn",
        db_path=str(tmp_path / "fof_rebalance_skip.db"),
        use_llm=False,
        config={"fof": {"sleeves": ["balanced"], "min_rebalance_weight_delta": 0.03}},
    )
    try:
        engine.current_portfolio["positions"] = {"AAA": {"shares": 100}}
        decisions = engine._rebalance_to_target_positions(
            target_positions={"AAA": 0.98},
            prices={"AAA": 10.0},
            date="2024-01-02",
            sleeve_weights={"balanced": 1.0},
            rationale="small drift",
        )
        assert decisions["AAA"]["action"] == "HOLD"
        assert engine.current_portfolio["positions"]["AAA"]["shares"] == 100
        assert engine._pending_rebalance_stats["skipped_trades"] == 1
        assert engine._pending_rebalance_stats["skip_reason_counts"]["weight_delta"] == 1
    finally:
        engine.close()



def test_fof_engine_records_min_shares_skip_reason(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)

    engine = FOFBacktestEngine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        initial_cash=0.0,
        market="cn",
        db_path=str(tmp_path / "fof_rebalance_min_shares.db"),
        use_llm=False,
        config={"fof": {"sleeves": ["balanced"], "min_rebalance_shares": 5}},
    )
    try:
        engine.current_portfolio["positions"] = {"AAA": {"shares": 100}}
        decisions = engine._rebalance_to_target_positions(
            target_positions={"AAA": 0.96},
            prices={"AAA": 10.0},
            date="2024-01-02",
            sleeve_weights={"balanced": 1.0},
            rationale="tiny share drift",
        )
        assert decisions["AAA"]["action"] == "HOLD"
        assert engine._pending_rebalance_stats["skip_reason_counts"]["min_shares"] == 1
    finally:
        engine.close()


def test_fof_engine_executes_rebalance_above_threshold(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)

    engine = FOFBacktestEngine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        initial_cash=0.0,
        market="cn",
        db_path=str(tmp_path / "fof_rebalance_apply.db"),
        use_llm=False,
        config={"fof": {"sleeves": ["balanced"], "min_rebalance_weight_delta": 0.03}},
    )
    try:
        engine.current_portfolio["positions"] = {"AAA": {"shares": 100}}
        decisions = engine._rebalance_to_target_positions(
            target_positions={"AAA": 0.90},
            prices={"AAA": 10.0},
            date="2024-01-02",
            sleeve_weights={"balanced": 1.0},
            rationale="large drift",
        )
        assert decisions["AAA"]["action"] == "SELL"
        assert decisions["AAA"]["shares"] == 10
        assert engine.current_portfolio["positions"]["AAA"]["shares"] == 90
        assert engine._pending_rebalance_stats["executed_trades"] == 1
        assert engine._pending_rebalance_stats["executed_turnover_ratio"] == 0.1
        assert engine._pending_rebalance_stats["total_turnover_ratio"] == 0.1
    finally:
        engine.close()


def test_fof_engine_bear_regime_raises_rebalance_threshold(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)

    engine = FOFBacktestEngine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        initial_cash=0.0,
        market="cn",
        db_path=str(tmp_path / "fof_bear_threshold.db"),
        use_llm=False,
        config={
            "fof": {
                "sleeves": ["balanced"],
                "min_rebalance_weight_delta": 0.02,
                "bear_rebalance_threshold_multiplier": 2.0,
            }
        },
    )
    try:
        assert engine._should_skip_rebalance_trade(
            current_weight=1.0,
            target_weight=0.97,
            trade_value=30.0,
            total_value=1000.0,
            trade_shares=3,
            regime="bear",
            sleeve_consensus={"average_pairwise_overlap": 1.0},
        ) is True
    finally:
        engine.close()



def test_fof_engine_low_consensus_raises_rebalance_threshold(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)

    engine = FOFBacktestEngine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        initial_cash=0.0,
        market="cn",
        db_path=str(tmp_path / "fof_consensus_threshold.db"),
        use_llm=False,
        config={
            "fof": {
                "sleeves": ["balanced"],
                "min_rebalance_weight_delta": 0.02,
                "low_consensus_overlap_threshold": 0.50,
                "low_consensus_threshold_multiplier": 2.0,
            }
        },
    )
    try:
        assert engine._should_skip_rebalance_trade(
            current_weight=1.0,
            target_weight=0.97,
            trade_value=30.0,
            total_value=1000.0,
            trade_shares=3,
            regime="neutral",
            sleeve_consensus={"average_pairwise_overlap": 0.30},
        ) is True
    finally:
        engine.close()


def test_fof_engine_backfills_previous_day_sleeve_attribution(monkeypatch, tmp_path: Path):
    import backtest.engine as engine_module

    _install_stub_portfolio_allocator(monkeypatch)
    monkeypatch.setattr(engine_module, "create_workflow_adapter", lambda **_: _FakeWorkflowAdapter())

    engine = FOFBacktestEngine(
        tickers=["AAA", "BBB"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        initial_cash=100000.0,
        market="cn",
        db_path=str(tmp_path / "fof_attr.db"),
        use_llm=True,
        analysts=["fundamental"],
        config={"fof": {"sleeves": ["conservative", "balanced", "aggressive", "passive"]}},
    )
    try:
        engine._generate_decisions("2024-01-02", {"AAA": 10.0, "BBB": 20.0})
        engine._generate_decisions("2024-01-03", {"AAA": 11.0, "BBB": 18.0})
        previous = engine.fof_daily_allocations[-2]
        latest = engine.fof_daily_allocations[-1]
        assert previous["attribution_complete"] is True
        assert "sleeve_returns" in previous
        assert "sleeve_contributions" in previous
        assert previous["sleeve_returns"]["balanced"] != 0.0
        assert latest["attribution_complete"] is False
        assert latest["sleeve_returns"]["balanced"] == 0.0
    finally:
        engine.close()



def test_fof_engine_total_turnover_ratio_only_counts_executed_trades(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)

    engine = FOFBacktestEngine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        initial_cash=0.0,
        market="cn",
        db_path=str(tmp_path / "fof_turnover_ratio.db"),
        use_llm=False,
        config={
            "fof": {
                "sleeves": ["balanced"],
                "min_rebalance_weight_delta": 0.01,
                "min_rebalance_trade_value_ratio": 0.06,
            }
        },
    )
    try:
        engine.current_portfolio["positions"] = {"AAA": {"shares": 100}}
        engine._rebalance_to_target_positions(
            target_positions={"AAA": 0.95},
            prices={"AAA": 10.0},
            date="2024-01-02",
            sleeve_weights={"balanced": 1.0},
            rationale="partial skip",
        )
        assert engine._pending_rebalance_stats["executed_turnover_ratio"] == 0.0
        assert engine._pending_rebalance_stats["skipped_turnover_ratio"] == 0.05
        assert engine._pending_rebalance_stats["total_turnover_ratio"] == 0.0
    finally:
        engine.close()

def test_fof_engine_rejects_unknown_sleeve(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)

    with pytest.raises(ValueError, match="Unknown FOF sleeve personality"):
        FOFBacktestEngine(
            tickers=["AAA"],
            start_date="2024-01-01",
            end_date="2024-01-05",
            initial_cash=100000.0,
            market="cn",
            db_path=str(tmp_path / "fof_invalid.db"),
            use_llm=False,
            config={"fof": {"sleeves": ["balanced", "mystery"]}},
        )


def test_fof_engine_rejects_meta_fof_sleeve(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)

    with pytest.raises(ValueError, match="cannot include the 'fof' meta personality"):
        FOFBacktestEngine(
            tickers=["AAA"],
            start_date="2024-01-01",
            end_date="2024-01-05",
            initial_cash=100000.0,
            market="cn",
            db_path=str(tmp_path / "fof_recursive.db"),
            use_llm=False,
            config={"fof": {"sleeves": ["balanced", "fof"]}},
        )


def test_fof_engine_rejects_nonpositive_sleeve_base_weight(monkeypatch, tmp_path: Path):
    _install_stub_portfolio_allocator(monkeypatch)

    with pytest.raises(ValueError, match="base_weight must be positive"):
        FOFBacktestEngine(
            tickers=["AAA"],
            start_date="2024-01-01",
            end_date="2024-01-05",
            initial_cash=100000.0,
            market="cn",
            db_path=str(tmp_path / "fof_bad_weight.db"),
            use_llm=False,
            config={"fof": {"sleeves": [{"personality": "balanced", "weight": 0}]}}
        )
