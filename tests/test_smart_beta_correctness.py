from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from backtest.smart_beta_engine import SmartBetaBacktestEngine
from backtest.engine import BacktestEngine
from deepfund.src.smart_beta.config import SmartBetaConfig
from deepfund.src.smart_beta.factor_engine import FactorData
from deepfund.src.smart_beta.index_constituents import IndexConstituentsProvider
from deepfund.src.smart_beta.news_freeze import NewsFreezeMechanism, FreezeDecision, FreezeReason, FreezeStatus
from deepfund.src.smart_beta.optimizer import SmartBetaOptimizer, OptimizationResult
from deepfund.src.smart_beta.smart_beta_allocator import SmartBetaAllocator, AllocationResult


class Constituent:
    def __init__(self, ticker, weight):
        self.ticker = ticker
        self.weight = weight


class FactorEngineStub:
    def batch_calculate_factors(self, tickers, stock_data_dict, market_data, trade_date):
        return {
            ticker: FactorData(
                ticker,
                trade_date,
                downside_beta=0.8,
                ivol=0.2,
                amihud=0.001,
                factor_score=0.5,
                is_valid=True,
            )
            for ticker in tickers
        }


class OptimizerSuccessStub:
    def __init__(self, target_weights, screened_tickers):
        self.target_weights = target_weights
        self.screened_tickers = screened_tickers

    def negative_screening(self, tickers, factor_data):
        return list(self.screened_tickers)

    def optimize(self, tickers, benchmark_weights, factor_data, current_weights, **kwargs):
        return type(
            "OptResult",
            (),
            {"success": True, "weights": dict(self.target_weights), "tracking_error": 0.02},
        )()

    def apply_turnover_constraint(self, target_weights, current_weights, turnover_limit):
        return dict(target_weights)


class OptimizerFailureStub(OptimizerSuccessStub):
    def optimize(self, tickers, benchmark_weights, factor_data, current_weights, **kwargs):
        return type(
            "OptResult",
            (),
            {"success": False, "weights": {}, "tracking_error": 0.0, "message": "failed"},
        )()


class NoFreezeStub:
    def check(self, market_volatility, market_return, news_items, current_date):
        return type(
            "FreezeDecisionStub",
            (),
            {
                "status": FreezeStatus.NONE,
                "is_active_at": lambda self, trade_date: False,
            },
        )()

    def get_active_freeze(self, current_date=None):
        return None


def make_allocator(optimizer, constituents=None):
    config = SmartBetaConfig(llm_adjustment_enabled=False, freeze_duration_days=5)
    allocator = SmartBetaAllocator(config)
    allocator.index_provider = type(
        "Provider",
        (),
        {
            "get_constituents": lambda self, index_code, td: constituents
            or [Constituent("AAPL", 0.6), Constituent("MSFT", 0.4)]
        },
    )()
    allocator.factor_engine = FactorEngineStub()
    allocator.optimizer = optimizer
    return allocator


def test_optimizer_skips_trust_constr_when_bounds_fix_all_variables():
    config = SmartBetaConfig(
        tracking_error_limit=1.0,
        max_stock_weight=1.0,
        require_downside_protection=False,
        min_weight=0.0,
    )
    optimizer = SmartBetaOptimizer(config)
    tickers = ["AAPL"]
    benchmark_weights = {"AAPL": 1.0}
    factor_data = {
        "AAPL": FactorData(
            ticker="AAPL",
            trade_date=datetime(2024, 1, 1),
            downside_beta=1.0,
            ivol=0.2,
            amihud=0.001,
            factor_score=0.5,
            is_valid=True,
        )
    }

    calls = []

    def fake_minimize(*args, **kwargs):
        calls.append(kwargs.get("method"))
        return SimpleNamespace(
            success=False,
            message="All independent variables were fixed by bounds",
        )

    with patch("deepfund.src.smart_beta.optimizer.minimize", side_effect=fake_minimize):
        result = optimizer.optimize(
            tickers,
            benchmark_weights,
            factor_data,
            returns_covariance=pd.DataFrame([[1.0]]).values,
            excluded_tickers=["AAPL"],
        )

    assert calls == ["SLSQP"]
    assert result.success is False
    assert result.weights == {"AAPL": 0.0}



def test_optimizer_still_tries_trust_constr_for_generic_slsqp_failures():
    config = SmartBetaConfig(
        tracking_error_limit=1.0,
        max_stock_weight=1.0,
        require_downside_protection=False,
        min_weight=0.0,
    )
    optimizer = SmartBetaOptimizer(config)
    tickers = ["AAPL"]
    benchmark_weights = {"AAPL": 1.0}
    factor_data = {
        "AAPL": FactorData(
            ticker="AAPL",
            trade_date=datetime(2024, 1, 1),
            downside_beta=1.0,
            ivol=0.2,
            amihud=0.001,
            factor_score=0.5,
            is_valid=True,
        )
    }

    calls = []

    def fake_minimize(*args, **kwargs):
        method = kwargs.get("method")
        calls.append(method)
        if method == "SLSQP":
            return SimpleNamespace(success=False, message="Singular Jacobian matrix")
        return SimpleNamespace(success=False, message="The maximum number of function evaluations is exceeded.")

    with patch("deepfund.src.smart_beta.optimizer.minimize", side_effect=fake_minimize):
        result = optimizer.optimize(
            tickers,
            benchmark_weights,
            factor_data,
            returns_covariance=pd.DataFrame([[1.0]]).values,
        )

    assert calls == ["SLSQP", "trust-constr"]
    assert result.success is False
    assert result.weights == benchmark_weights



def test_optimizer_enforces_tracking_error_limit():
    config = SmartBetaConfig(
        tracking_error_limit=0.01,
        max_stock_weight=1.0,
        require_downside_protection=True,
        downside_beta_gamma=0.1,
        min_weight=0.0,
    )
    optimizer = SmartBetaOptimizer(config)

    tickers = ["LOW", "HIGH"]
    benchmark_weights = {"LOW": 0.5, "HIGH": 0.5}
    factor_data = {
        "LOW": FactorData(
            ticker="LOW",
            trade_date=datetime(2024, 1, 1),
            downside_beta=0.0,
            ivol=0.2,
            amihud=0.001,
            factor_score=0.5,
            is_valid=True,
        ),
        "HIGH": FactorData(
            ticker="HIGH",
            trade_date=datetime(2024, 1, 1),
            downside_beta=2.0,
            ivol=0.2,
            amihud=0.001,
            factor_score=0.5,
            is_valid=True,
        ),
    }

    result = optimizer.optimize(
        tickers,
        benchmark_weights,
        factor_data,
        returns_covariance=pd.DataFrame([[1.0, 0.0], [0.0, 1.0]]).values,
    )

    assert not result.success
    assert result.tracking_error == 0
    assert result.weights == benchmark_weights
    assert "Optimization" in result.message



def test_news_freeze_uses_backtest_date_semantics():
    mechanism = NewsFreezeMechanism(SmartBetaConfig(freeze_duration_days=5))
    start = datetime(2024, 1, 1)

    decision = mechanism.check(market_return=-0.1, current_date=start)
    assert decision.is_active_at(datetime(2023, 12, 31)) is False
    assert decision.is_active_at(datetime(2024, 1, 3)) is True
    assert mechanism.should_freeze_trading(datetime(2024, 1, 3)) is True
    assert mechanism.should_freeze_trading(datetime(2024, 1, 10)) is False
    assert mechanism.get_active_freeze(datetime(2023, 12, 31)) is None
    assert mechanism.get_active_freeze(datetime(2024, 1, 3)) is decision
    assert mechanism.get_active_freeze(datetime(2024, 1, 10)) is None


def test_news_freeze_counts_trading_days_not_weekends():
    mechanism = NewsFreezeMechanism(SmartBetaConfig(freeze_duration_days=5))
    start = datetime(2024, 1, 5)  # Friday

    decision = mechanism.check(market_return=-0.1, current_date=start)

    assert mechanism.should_freeze_trading(datetime(2024, 1, 10)) is True  # Wednesday
    assert mechanism.should_freeze_trading(datetime(2024, 1, 11)) is True  # Thursday, 5th session
    assert mechanism.should_freeze_trading(datetime(2024, 1, 12)) is False  # Friday should be released
    assert mechanism.should_freeze_trading(datetime(2024, 1, 15)) is False
    assert decision.days_remaining_at(datetime(2024, 1, 8)) == 3
    assert decision.reason == FreezeReason.MARKET_DROP



def test_freeze_decision_to_dict_uses_reference_date():
    decision = FreezeDecision(
        status=FreezeStatus.ACTIVE,
        reason=FreezeReason.MARKET_DROP,
        duration_days=5,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 6),
        confidence=0.8,
        triggers=["drop"],
    )

    payload = decision.to_dict(datetime(2024, 1, 3))

    assert payload["is_active"] is True
    assert payload["days_remaining"] == 2



def test_allocation_result_to_dict_uses_timestamp_for_freeze_state():
    freeze = FreezeDecision(
        status=FreezeStatus.ACTIVE,
        reason=FreezeReason.MARKET_DROP,
        duration_days=5,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 6),
        confidence=0.8,
        triggers=["drop"],
    )
    result = AllocationResult(
        weights={"AAPL": 1.0},
        benchmark_weights={"AAPL": 1.0},
        freeze_decision=freeze,
        timestamp=datetime(2024, 1, 3),
        success=True,
    )

    payload = result.to_dict()

    assert payload["freeze_active"] is True
    assert payload["freeze_decision"]["days_remaining"] == 2


def test_allocation_result_to_dict_emits_stable_inactive_freeze_schema():
    result = AllocationResult(
        weights={"AAPL": 1.0},
        benchmark_weights={"AAPL": 1.0},
        timestamp=datetime(2024, 1, 3),
        success=True,
    )

    payload = result.to_dict()

    assert payload["freeze_active"] is False
    assert payload["freeze_decision"]["status"] == FreezeStatus.NONE.value
    assert payload["freeze_decision"]["reason"] == FreezeReason.NONE.value
    assert payload["freeze_decision"]["days_remaining"] == 0



def test_allocator_prompt_context_uses_allocation_timestamp_for_freeze_state():
    allocator = make_allocator(OptimizerSuccessStub(target_weights={"AAPL": 1.0}, screened_tickers=["AAPL"]))
    freeze = FreezeDecision(
        status=FreezeStatus.ACTIVE,
        reason=FreezeReason.MARKET_DROP,
        duration_days=5,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 6),
        confidence=0.8,
        triggers=["drop"],
    )
    allocator.news_freeze._active_freeze = FreezeDecision()  # Deliberately stale allocator state.
    allocation = AllocationResult(
        weights={"AAPL": 1.0},
        benchmark_weights={"AAPL": 1.0},
        freeze_decision=freeze,
        timestamp=datetime(2024, 1, 3),
        success=True,
    )

    context = allocator.get_llm_prompt_context(allocation)

    assert context["freeze_status"]["freeze_active"] is True
    assert context["freeze_status"]["days_remaining"] == 2



def test_allocator_reverts_to_full_benchmark_on_historical_freeze():
    trade_date = datetime(2024, 1, 1)
    constituents = [Constituent("AAPL", 0.5), Constituent("MSFT", 0.3), Constituent("NVDA", 0.2)]
    allocator = make_allocator(
        OptimizerSuccessStub(target_weights={"AAPL": 0.2, "MSFT": 0.8}, screened_tickers=["AAPL", "MSFT"]),
        constituents=constituents,
    )

    allocation = allocator.allocate(
        trade_date=trade_date,
        stock_data={},
        market_data=pd.DataFrame({"close": [100.0, 94.0]}, index=pd.to_datetime(["2023-12-29", "2024-01-01"])),
        current_portfolio={"AAPL": 0, "MSFT": 0, "NVDA": 0},
        prices={"AAPL": 100.0, "MSFT": 100.0, "NVDA": 100.0},
        macro_indicators=None,
        news_items=None,
        market_return_today=-0.1,
    )

    assert allocation.success is True
    assert allocation.freeze_decision is not None
    assert allocation.freeze_decision.status == FreezeStatus.ACTIVE
    assert allocation.weights == {"AAPL": 0.5, "MSFT": 0.3, "NVDA": 0.2}
    assert allocation.tracking_error == 0.0



def test_allocator_optimization_failure_reverts_to_full_benchmark():
    constituents = [Constituent("AAPL", 0.5), Constituent("MSFT", 0.3), Constituent("NVDA", 0.2)]
    allocator = make_allocator(
        OptimizerFailureStub(target_weights={}, screened_tickers=["AAPL", "MSFT"]),
        constituents=constituents,
    )
    allocator.news_freeze = NoFreezeStub()

    allocation = allocator.allocate(
        trade_date=datetime(2024, 1, 1),
        stock_data={},
        market_data=pd.DataFrame({"close": [100.0, 101.0]}, index=pd.to_datetime(["2023-12-29", "2024-01-01"])),
        current_portfolio={"AAPL": 0, "MSFT": 0, "NVDA": 0},
        prices={"AAPL": 100.0, "MSFT": 100.0, "NVDA": 100.0},
        macro_indicators=None,
        news_items=None,
        market_return_today=0.01,
    )

    assert allocation.success is True
    assert allocation.weights == {"AAPL": 0.5, "MSFT": 0.3, "NVDA": 0.2}



def test_allocator_current_weights_include_cash():
    allocator = make_allocator(OptimizerSuccessStub(target_weights={"AAPL": 0.5}, screened_tickers=["AAPL"]))

    weights = allocator._calculate_current_weights(
        current_portfolio={
            "positions": {"AAPL": {"shares": 10}},
            "cashflow": 1000.0,
        },
        prices={"AAPL": 100.0},
        tickers=["AAPL"],
    )

    assert abs(weights["AAPL"] - 0.5) < 1e-9



def test_turnover_constraint_counts_cash_bucket():
    optimizer = SmartBetaOptimizer(SmartBetaConfig(turnover_limit=0.30))

    adjusted = optimizer.apply_turnover_constraint(
        target_weights={"AAPL": 1.0},
        current_weights={"AAPL": 0.5},
        turnover_limit=0.30,
    )

    assert abs(adjusted["AAPL"] - 0.8) < 1e-9



def test_allocator_reports_turnover_with_cash_bucket():
    allocator = make_allocator(OptimizerSuccessStub(target_weights={"AAPL": 0.8}, screened_tickers=["AAPL"]))

    turnover = allocator._calculate_turnover_with_cash(
        target_weights={"AAPL": 0.8},
        current_weights={"AAPL": 0.5},
    )

    assert abs(turnover - 0.30) < 1e-9



def test_allocator_reports_tracking_error_from_final_weights():
    allocator = make_allocator(OptimizerSuccessStub(target_weights={"AAPL": 1.0}, screened_tickers=["AAPL"]))
    optimization_result = OptimizationResult(
        weights={"AAPL": 1.0},
        tracking_error=0.0,
        success=True,
        benchmark_vector={"AAPL": 1.0},
        covariance_matrix=[[0.000001]],
    )

    te = allocator._calculate_tracking_error(
        target_weights={"AAPL": 0.8},
        benchmark_weights={"AAPL": 1.0},
        optimization_result=optimization_result,
    )

    expected = ((0.2 ** 2) * 0.000001 * allocator.config.market_days_per_year) ** 0.5
    assert abs(te - expected) < 1e-12



def test_allocator_normalizes_cn_suffixes_between_constituents_and_backtest_inputs():
    trade_date = datetime(2024, 1, 2)
    allocator = make_allocator(
        OptimizerSuccessStub(target_weights={"600519": 1.0}, screened_tickers=["600519"]),
        constituents=[Constituent("600519.SH", 1.0)],
    )
    allocator.news_freeze = NoFreezeStub()

    allocation = allocator.allocate(
        trade_date=trade_date,
        stock_data={
            "600519": pd.DataFrame(
                {
                    "close": [100.0 + i for i in range(80)],
                    "volume": [1000.0 for _ in range(80)],
                },
                index=pd.date_range("2023-09-01", periods=80, freq="B"),
            )
        },
        market_data=pd.DataFrame(
            {"close": [100.0 + i * 0.5 for i in range(80)]},
            index=pd.date_range("2023-09-01", periods=80, freq="B"),
        ),
        current_portfolio={"positions": {"600519": {"shares": 0}}, "cashflow": 100000.0},
        prices={"600519": 100.0},
        macro_indicators=None,
        news_items=None,
        market_return_today=0.01,
    )

    assert allocation.success is True
    assert allocation.weights == {"600519": 1.0}



def test_trading_decisions_sell_before_buy_for_rotation():
    allocator = make_allocator(OptimizerSuccessStub(target_weights={"MSFT": 1.0}, screened_tickers=["MSFT"]))
    allocation = AllocationResult(weights={"MSFT": 1.0}, benchmark_weights={"MSFT": 1.0}, success=True)

    decisions = allocator.get_trading_decisions(
        allocation=allocation,
        current_portfolio={"AAPL": 10, "MSFT": 0},
        prices={"AAPL": 100.0, "MSFT": 100.0},
        total_capital=1000.0,
    )

    assert [d["action"] for d in decisions] == ["Sell", "Buy"]
    assert [d["ticker"] for d in decisions] == ["AAPL", "MSFT"]



def test_execute_day_with_decisions_sells_before_buys_when_ordered():
    engine = BacktestEngine.__new__(BacktestEngine)
    engine.current_portfolio = {
        "cashflow": 0.0,
        "positions": {
            "AAPL": {"shares": 10, "value": 1000.0},
            "MSFT": {"shares": 0, "value": 0.0},
        },
    }
    engine.broker_audit_events = []

    class Tracker:
        def __init__(self):
            self.trades = []
            self.snapshot_called = False

        def record_trade(self, date, ticker, action, shares, price):
            self.trades.append((action, ticker, shares, price))

        def record_snapshot(self, date, cashflow, positions, prices):
            self.snapshot_called = True

    engine.tracker = Tracker()

    prices = {"AAPL": 100.0, "MSFT": 100.0}
    decisions = {
        "AAPL": {"action": "SELL", "shares": 10},
        "MSFT": {"action": "BUY", "shares": 10},
    }

    BacktestEngine._execute_day_with_decisions(engine, "2024-01-02", prices, decisions)

    assert engine.current_portfolio["cashflow"] == 0.0
    assert engine.current_portfolio["positions"]["AAPL"]["shares"] == 0
    assert engine.current_portfolio["positions"]["MSFT"]["shares"] == 10
    assert engine.tracker.trades == [("SELL", "AAPL", 10, 100.0), ("BUY", "MSFT", 10, 100.0)]
    assert engine.tracker.snapshot_called is True



def test_allocator_honors_existing_freeze_without_new_inputs():
    constituents = [Constituent("AAPL", 0.5), Constituent("MSFT", 0.5)]
    allocator = make_allocator(
        OptimizerSuccessStub(target_weights={"AAPL": 1.0}, screened_tickers=["AAPL"]),
        constituents=constituents,
    )
    active_freeze = FreezeDecision(
        status=FreezeStatus.ACTIVE,
        reason=FreezeReason.MARKET_DROP,
        duration_days=5,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 5),
        confidence=0.8,
        triggers=["drop"],
    )

    class PersistentFreeze:
        def get_active_freeze(self, current_date=None):
            return active_freeze if current_date and current_date <= datetime(2024, 1, 5) else None

        def check(self, market_volatility, market_return, news_items, current_date):
            return active_freeze

    allocator.news_freeze = PersistentFreeze()

    allocation = allocator.allocate(
        trade_date=datetime(2024, 1, 3),
        stock_data={},
        market_data=pd.DataFrame({"close": [100.0, 101.0]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"])),
        current_portfolio={"AAPL": 0, "MSFT": 0},
        prices={"AAPL": 100.0, "MSFT": 100.0},
        macro_indicators=None,
        news_items=None,
        market_return_today=None,
    )

    assert allocation.freeze_decision is active_freeze
    assert allocation.weights == {"AAPL": 0.5, "MSFT": 0.5}



def test_allocator_triggers_freeze_from_volatility_only_signal():
    constituents = [Constituent("AAPL", 0.5), Constituent("MSFT", 0.5)]
    allocator = make_allocator(
        OptimizerSuccessStub(target_weights={"AAPL": 1.0}, screened_tickers=["AAPL"]),
        constituents=constituents,
    )

    class VolatilityFreeze:
        def __init__(self):
            self.seen_volatility = None

        def get_active_freeze(self, current_date=None):
            return None

        def check(self, market_volatility, market_return, news_items, current_date):
            self.seen_volatility = market_volatility
            return FreezeDecision(
                status=FreezeStatus.ACTIVE,
                reason=FreezeReason.VOLATILITY,
                duration_days=5,
                start_date=current_date,
                end_date=current_date,
                confidence=0.8,
                triggers=["volatility"],
            )

    freeze = VolatilityFreeze()
    allocator.news_freeze = freeze

    market_data = pd.DataFrame(
        {"close": [100, 120, 80, 130, 70, 125, 75, 135, 65, 140, 60, 145, 55, 150, 50, 155, 45, 160, 40, 165, 35, 170]},
        index=pd.date_range("2024-01-01", periods=22, freq="D"),
    )

    allocation = allocator.allocate(
        trade_date=datetime(2024, 1, 22),
        stock_data={},
        market_data=market_data,
        current_portfolio={"AAPL": 0, "MSFT": 0},
        prices={"AAPL": 100.0, "MSFT": 100.0},
        macro_indicators=None,
        news_items=None,
        market_return_today=None,
    )

    assert freeze.seen_volatility is not None
    assert allocation.freeze_decision is not None
    assert allocation.freeze_decision.reason == FreezeReason.VOLATILITY
    assert allocation.weights == {"AAPL": 0.5, "MSFT": 0.5}



def test_prepare_market_data_prefers_provider_index_series():
    engine = SmartBetaBacktestEngine.__new__(SmartBetaBacktestEngine)
    engine.market = "us"
    engine.index_code = "^GSPC"
    engine.tickers = ["AAPL", "MSFT"]

    expected = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [1000, 1100],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
    )
    expected.index.name = "date"

    class Provider:
        def get_index_daily(self, index_code, start_date, end_date):
            return expected

    class DummyDB:
        def get_stock_prices(self, ticker, start_date, end_date):
            raise AssertionError("Synthetic fallback should not be used when provider returns data")

    engine.index_provider = Provider()
    engine.prefetcher = type("Prefetcher", (), {"db": DummyDB()})()

    market_data = SmartBetaBacktestEngine._prepare_market_data(engine, datetime(2024, 1, 2))

    pd.testing.assert_frame_equal(market_data, expected)



def test_generate_smart_beta_decisions_passes_cash_to_allocator():
    engine = SmartBetaBacktestEngine.__new__(SmartBetaBacktestEngine)
    engine.tickers = ["AAPL"]
    engine.current_portfolio = {
        "cashflow": 1000.0,
        "positions": {"AAPL": {"shares": 10, "value": 1000.0}},
    }
    engine.initial_cash = 1000.0
    engine.last_rebalance_date = None
    engine.smart_beta_available = True
    engine._prepare_stock_data = lambda date: {}
    engine._prepare_market_data = lambda date: pd.DataFrame({"close": [100.0, 101.0]}, index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    engine._get_macro_indicators = lambda date: None
    engine._get_news_items = lambda date: None
    engine._calculate_market_return = lambda market_data: None

    captured = {}

    class Allocator:
        def allocate(self, **kwargs):
            captured["current_portfolio"] = kwargs["current_portfolio"]
            return AllocationResult(weights={"AAPL": 1.0}, benchmark_weights={"AAPL": 1.0}, success=True)

        def get_trading_decisions(self, allocation, current_portfolio, prices, total_capital):
            captured["decision_portfolio"] = current_portfolio
            return []

    engine.smart_beta_allocator = Allocator()

    decisions = SmartBetaBacktestEngine._generate_smart_beta_decisions(
        engine,
        datetime(2024, 1, 2),
        {"AAPL": 100.0},
    )

    assert decisions["AAPL"]["action"] == "HOLD"
    assert decisions["AAPL"]["_applied"] is False
    assert captured["current_portfolio"]["cashflow"] == 1000.0
    assert captured["current_portfolio"]["positions"]["AAPL"]["shares"] == 10
    assert captured["decision_portfolio"]["cashflow"] == 1000.0


def test_generate_smart_beta_trade_decisions_mark_unapplied():
    engine = SmartBetaBacktestEngine.__new__(SmartBetaBacktestEngine)
    engine.tickers = ["AAPL"]
    engine.current_portfolio = {"cashflow": 1000.0, "positions": {}}
    engine.initial_cash = 1000.0
    engine.last_rebalance_date = None
    engine.smart_beta_available = True
    engine._prepare_stock_data = lambda date: {}
    engine._prepare_market_data = lambda date: pd.DataFrame({"close": [100.0, 101.0]}, index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    engine._get_macro_indicators = lambda date: None
    engine._get_news_items = lambda date: None
    engine._calculate_market_return = lambda market_data: None

    class Allocator:
        def allocate(self, **kwargs):
            return AllocationResult(weights={"AAPL": 1.0}, benchmark_weights={"AAPL": 1.0}, success=True)

        def get_trading_decisions(self, allocation, current_portfolio, prices, total_capital):
            return [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "shares": 2,
                    "price": 100.0,
                    "target_weight": 0.2,
                }
            ]

    engine.smart_beta_allocator = Allocator()

    decisions = SmartBetaBacktestEngine._generate_smart_beta_decisions(
        engine,
        datetime(2024, 1, 2),
        {"AAPL": 100.0},
    )

    assert decisions["AAPL"]["action"] == "BUY"
    assert decisions["AAPL"]["shares"] == 2
    assert decisions["AAPL"]["_applied"] is False



def test_fetch_us_index_daily_includes_requested_end_date():
    provider = IndexConstituentsProvider()
    captured = {}

    fake_df = pd.DataFrame(
        {
            "Open": [1.0],
            "High": [1.0],
            "Low": [1.0],
            "Close": [1.0],
            "Volume": [100],
        },
        index=pd.to_datetime(["2024-01-02"]),
    )

    def fake_download(symbol, start, end, progress, auto_adjust):
        captured["symbol"] = symbol
        captured["start"] = start
        captured["end"] = end
        return fake_df

    with patch("importlib.import_module") as import_module:
        import_module.return_value = type("YF", (), {"download": staticmethod(fake_download)})()
        result = provider._fetch_us_index_daily("^GSPC", datetime(2024, 1, 1), datetime(2024, 1, 2))

    assert captured["symbol"] == "^GSPC"
    assert captured["start"] == "2024-01-01"
    assert captured["end"] == "2024-01-03"
    assert list(result.index.strftime("%Y-%m-%d")) == ["2024-01-02"]


def test_us_index_constituents_use_fallback_without_tushare():
    class Provider(IndexConstituentsProvider):
        @property
        def tushare_api(self):
            raise AssertionError("US index constituents should not construct Tushare")

    provider = Provider()

    constituents = provider.get_constituents("^GSPC", datetime(2024, 1, 2))

    assert constituents
    assert {item.ticker for item in constituents} >= {"AAPL", "MSFT", "NVDA"}
    assert abs(sum(item.weight for item in constituents) - 1.0) < 1e-9



def test_fallback_constituent_weights_are_normalized():
    provider = IndexConstituentsProvider()
    constituents = provider._fetch_constituents_fallback("000300.SH", datetime(2024, 1, 1))

    assert constituents
    total_weight = sum(item.weight for item in constituents)
    assert abs(total_weight - 1.0) < 1e-9



def test_optimizer_reports_annualized_tracking_error():
    config = SmartBetaConfig(
        tracking_error_limit=0.03,
        max_stock_weight=1.0,
        require_downside_protection=True,
        downside_beta_gamma=0.1,
        min_weight=0.0,
    )
    optimizer = SmartBetaOptimizer(config)
    tickers = ["LOW", "HIGH"]
    benchmark_weights = {"LOW": 0.5, "HIGH": 0.5}
    factor_data = {
        "LOW": FactorData("LOW", datetime(2024, 1, 1), downside_beta=0.0, ivol=0.2, amihud=0.001, factor_score=0.5, is_valid=True),
        "HIGH": FactorData("HIGH", datetime(2024, 1, 1), downside_beta=2.0, ivol=0.2, amihud=0.001, factor_score=0.5, is_valid=True),
    }
    cov = pd.DataFrame([[0.000001, 0.0], [0.0, 0.000001]]).values

    result = optimizer.optimize(tickers, benchmark_weights, factor_data, returns_covariance=cov)

    expected_annual_te = ((2 * (0.05 ** 2) * 0.000001 * config.market_days_per_year) ** 0.5)
    assert result.success is True
    assert result.tracking_error > 0
    assert abs(result.tracking_error - expected_annual_te) < 1e-6
    assert result.tracking_error <= config.tracking_error_limit + 1e-9



def test_optimizer_keeps_screened_names_at_zero_against_full_benchmark():
    config = SmartBetaConfig(
        tracking_error_limit=1.0,
        max_stock_weight=1.0,
        require_downside_protection=False,
        min_weight=0.0,
    )
    optimizer = SmartBetaOptimizer(config)
    tickers = ["AAPL", "MSFT", "NVDA"]
    benchmark_weights = {"AAPL": 0.4, "MSFT": 0.3, "NVDA": 0.3}
    factor_data = {
        t: FactorData(t, datetime(2024, 1, 1), downside_beta=1.0, ivol=0.2, amihud=0.001, factor_score=0.5, is_valid=True)
        for t in tickers
    }
    cov = pd.DataFrame(
        [[0.000001, 0.0, 0.0], [0.0, 0.000001, 0.0], [0.0, 0.0, 0.000001]],
    ).values

    result = optimizer.optimize(
        tickers,
        benchmark_weights,
        factor_data,
        returns_covariance=cov,
        excluded_tickers=["NVDA"],
    )

    assert result.success is True
    assert abs(result.weights["NVDA"]) < 1e-12
    assert result.tracking_error > 0



def test_optimizer_recomputes_te_after_min_weight_pruning():
    config = SmartBetaConfig(
        tracking_error_limit=1.0,
        max_stock_weight=1.0,
        require_downside_protection=False,
        min_weight=0.1,
    )
    optimizer = SmartBetaOptimizer(config)
    tickers = ["AAPL", "MSFT", "NVDA"]
    benchmark_weights = {"AAPL": 0.999, "MSFT": 0.0005, "NVDA": 0.0005}
    factor_data = {
        t: FactorData(t, datetime(2024, 1, 1), downside_beta=1.0, ivol=0.2, amihud=0.001, factor_score=0.5, is_valid=True)
        for t in tickers
    }
    cov = pd.DataFrame(
        [[0.000001, 0.0, 0.0], [0.0, 0.000001, 0.0], [0.0, 0.0, 0.000001]],
    ).values

    result = optimizer.optimize(
        tickers,
        benchmark_weights,
        factor_data,
        returns_covariance=cov,
    )

    assert result.success is True
    assert result.weights["MSFT"] == 0.0
    assert result.weights["NVDA"] == 0.0
    assert result.tracking_error > 0



def test_optimizer_fails_if_pruned_portfolio_breaks_te_limit():
    config = SmartBetaConfig(
        tracking_error_limit=0.03,
        max_stock_weight=1.0,
        require_downside_protection=False,
        min_weight=0.15,
    )
    optimizer = SmartBetaOptimizer(config)
    tickers = ["AAPL", "MSFT", "NVDA"]
    benchmark_weights = {"AAPL": 0.8, "MSFT": 0.1, "NVDA": 0.1}
    factor_data = {
        t: FactorData(t, datetime(2024, 1, 1), downside_beta=1.0, ivol=0.2, amihud=0.001, factor_score=0.5, is_valid=True)
        for t in tickers
    }
    cov = pd.DataFrame(
        [[0.01, 0.0, 0.0], [0.0, 0.01, 0.0], [0.0, 0.0, 0.01]],
    ).values

    result = optimizer.optimize(
        tickers,
        benchmark_weights,
        factor_data,
        returns_covariance=cov,
    )

    assert result.success is False
    assert result.tracking_error == 0
    assert "tracking_error_limit" in result.message



def test_crisis_news_sets_reason_when_no_other_trigger():
    mechanism = NewsFreezeMechanism(SmartBetaConfig(freeze_duration_days=5))

    decision = mechanism.check(
        news_items=[{"title": "Liquidity crisis spreads", "content": "systemic risk rising"}],
        current_date=datetime(2024, 1, 2),
    )

    assert decision.reason == FreezeReason.CRISIS_NEWS
    assert decision.status == FreezeStatus.ACTIVE
    assert decision.is_active_at(datetime(2024, 1, 2)) is True



def test_macro_indicators_disabled_without_real_source():
    engine = SmartBetaBacktestEngine.__new__(SmartBetaBacktestEngine)
    assert SmartBetaBacktestEngine._get_macro_indicators(engine, datetime(2024, 1, 1)) is None
