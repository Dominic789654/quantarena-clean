"""Tests for day-level multi-personality orchestration."""

from pathlib import Path
import builtins
import json
import sys
import tempfile
import threading
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for extra_path in (
    PROJECT_ROOT,
    PROJECT_ROOT / "deepear" / "src",
    PROJECT_ROOT / "deepfund" / "src",
):
    extra_path_str = str(extra_path)
    if extra_path_str not in sys.path:
        sys.path.insert(0, extra_path_str)

from llm.inference import get_token_stats, record_token_usage
from backtest.engine import BacktestResult
from backtest.workflow_adapter import BacktestWorkflowAdapter, SharedPhase1Artifact
from backtest.portfolio_tracker import PortfolioTracker
from backtest.multi_personality_engine import MultiPersonalityBacktest
from quantarena.news_diagnostics import clear_news_diagnostics, peek_news_diagnostics, record_news_diagnostic


class FakeSharedCache:
    def __init__(self):
        self._stats = {
            "execution_mode": "day_shared_phase1",
            "shared_phase1_days": 0,
            "shared_phase1_errors": 0,
            "shared_phase1_token_usage": {"total_input": 0, "total_output": 0, "calls": 0, "by_agent": {}},
        }
        self._prices = {
            "2026-01-02": {"AAA": 100.0, "BBB": 200.0},
            "2026-01-05": {"AAA": 101.0, "BBB": 198.0},
        }

    def get_trading_days(self):
        return list(self._prices.keys())

    def get_prices_for_date(self, date):
        return self._prices.get(date, {})

    def close(self):
        return None


class FakeSharedSignalAdapter:
    def __init__(self):
        self.calls = []

    def collect_signals_only_parallel_v2(self, trading_date, prices, max_workers=5):
        self.calls.append((trading_date, tuple(sorted(prices.keys())), max_workers))
        record_token_usage("shared_phase1", 10, 5)
        return {
            ticker: {
                "ticker": ticker,
                "analyst_signals": [f"signal-{ticker}-{trading_date}"],
                "priority_score": 1.0,
                "summary": {},
            }
            for ticker in prices
        }

    def load_or_compute_shared_phase1(self, trading_date, prices, max_workers=5):
        enhanced_signals = self.collect_signals_only_parallel_v2(trading_date, prices, max_workers=max_workers)
        return SharedPhase1Artifact(
            trading_date=trading_date,
            prices=dict(prices),
            enhanced_signals=enhanced_signals,
            priority_order=list(enhanced_signals.keys()),
            metadata={"cache_hit": False, "artifact_version": "v2"},
        )

    def close(self):
        return None


class FakeBacktestEngine:
    instances = []

    def __init__(
        self,
        tickers,
        start_date,
        end_date,
        initial_cash=100000.0,
        market="cn",
        config=None,
        db_path="data/signal_flux.db",
        use_llm=False,
        analysts=None,
        personality="balanced",
        portfolio_mode=True,
        smart_priority_mode=True,
        shared_analyst_cache_dir=None,
        shared_phase1_cache_dir=None,
    ):
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.initial_cash = initial_cash
        self.market = market
        self.config = config
        self.personality = personality
        self.use_llm = use_llm
        self.smart_priority_mode = smart_priority_mode
        self.workflow_adapter = object()
        self.current_portfolio = {
            "cashflow": initial_cash,
            "positions": {ticker: {"shares": 0, "value": 0.0} for ticker in tickers},
        }
        self.precollected_calls = []
        self.executed_days = []
        FakeBacktestEngine.instances.append(self)

    def _is_equal_weight_personality(self):
        return False

    def _generate_llm_decisions_with_precollected_signals(self, date, prices, enhanced_signals, priority_order=None):
        self.precollected_calls.append((date, tuple(sorted(enhanced_signals.keys()))))
        record_token_usage(f"phase2_{self.personality}", 3, 2)
        return {
            ticker: {
                "action": "HOLD",
                "shares": 0,
                "price": prices[ticker],
                "justification": f"shared-{self.personality}",
                "_applied": True,
            }
            for ticker in prices
        }

    def _generate_decisions(self, date, prices):
        raise AssertionError("day orchestrator should not fall back to per-personality phase1")

    def _execute_day_with_decisions(self, date, prices, decisions):
        self.executed_days.append((date, decisions))

    def finalize_run(self, trading_days, run_id=None, generate_report=True, errors=None, token_stats_override=None):
        tracker = PortfolioTracker(initial_cash=self.initial_cash)
        return BacktestResult(
            run_id=run_id or f"fake_{self.personality}",
            start_date=self.start_date,
            end_date=self.end_date,
            tickers=self.tickers,
            market=self.market,
            initial_cash=self.initial_cash,
            tracker=tracker,
            metrics={
                "total_return": 1.23,
                "max_drawdown": 2.34,
                "sharpe_ratio": 0.56,
                "total_trades": 0,
                "win_rate": 0.0,
                "avg_position_days": 0.0,
            },
            errors=list(errors or []),
        )

    def close(self):
        return None


def test_multi_personality_run_shares_phase1_once_per_day(monkeypatch):
    FakeBacktestEngine.instances = []
    shared_adapter = FakeSharedSignalAdapter()

    monkeypatch.setattr("backtest.multi_personality_engine.BacktestEngine", FakeBacktestEngine)
    monkeypatch.setattr(
        "backtest.multi_personality_engine.create_workflow_adapter",
        lambda **kwargs: shared_adapter,
    )

    backtest = MultiPersonalityBacktest(
        tickers=["AAA", "BBB"],
        start_date="2026-01-02",
        end_date="2026-01-05",
        personalities=["balanced", "aggressive"],
        use_llm=True,
        analysts=["fundamental"],
    )
    backtest.shared_cache = FakeSharedCache()

    comparison = backtest.run(prefetch=False, generate_report=False)

    assert comparison.trading_days == 2
    assert shared_adapter.calls == [
        ("2026-01-02", ("AAA", "BBB"), 2),
        ("2026-01-05", ("AAA", "BBB"), 2),
    ]
    assert set(comparison.personality_results.keys()) == {"balanced", "aggressive"}

    for engine in FakeBacktestEngine.instances:
        assert engine.precollected_calls == [
            ("2026-01-02", ("AAA", "BBB")),
            ("2026-01-05", ("AAA", "BBB")),
        ]
        assert [day for day, _ in engine.executed_days] == ["2026-01-02", "2026-01-05"]

    assert comparison.shared_data_stats["shared_phase1_days"] == 2


def test_multi_personality_report_exports_daily_decisions_and_news_diagnostics(monkeypatch, tmp_path):
    FakeBacktestEngine.instances = []
    clear_news_diagnostics()
    record_news_diagnostic(
        {
            "provider": "fmp",
            "market": "us",
            "ticker": "AAA",
            "trading_date": "2026-01-02",
            "raw_count": 1,
            "date_filtered_count": 1,
            "ticker_filtered_count": 0,
            "topic_filtered_count": 0,
            "final_count": 0,
            "stages": [{"endpoint": "/stable/news/general-latest", "raw_count": 1, "final_count": 0}],
        }
    )
    shared_adapter = FakeSharedSignalAdapter()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("backtest.multi_personality_engine.BacktestEngine", FakeBacktestEngine)
    monkeypatch.setattr(
        "backtest.multi_personality_engine.create_workflow_adapter",
        lambda **kwargs: shared_adapter,
    )

    backtest = MultiPersonalityBacktest(
        tickers=["AAA", "BBB"],
        start_date="2026-01-02",
        end_date="2026-01-05",
        personalities=["balanced"],
        use_llm=True,
        analysts=["fundamental"],
    )
    backtest.shared_cache = FakeSharedCache()

    comparison = backtest.run(prefetch=False, generate_report=True)
    report_dir = tmp_path / "reports" / "multi_personality" / comparison.run_id

    decision_rows = [
        json.loads(line)
        for line in (report_dir / "daily_decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    news_rows = [
        json.loads(line)
        for line in (report_dir / "news_diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert len(decision_rows) == 4
    assert decision_rows[0] == {
        "action": "HOLD",
        "applied": True,
        "date": "2026-01-02",
        "justification": "shared-balanced",
        "metadata": {"_applied": True},
        "personality": "balanced",
        "price": 100.0,
        "risk_reasons": [],
        "shares": 0,
        "ticker": "AAA",
    }
    assert news_rows[0]["provider"] == "fmp"
    assert news_rows[0]["ticker"] == "AAA"
    assert news_rows[0]["raw_count"] == 1
    assert peek_news_diagnostics() == []


def test_multi_personality_decision_record_preserves_false_applied_state():
    record = MultiPersonalityBacktest._normalize_decision_record(
        date="2026-01-02",
        personality="smart_beta_passive",
        ticker="AAA",
        decision={
            "action": "HOLD",
            "shares": 0,
            "justification": "No rebalancing scheduled",
            "_applied": False,
        },
    )

    assert record["applied"] is False
    assert record["metadata"] == {"_applied": False}


class FailingBacktestEngine(FakeBacktestEngine):
    def _generate_llm_decisions_with_precollected_signals(self, date, prices, enhanced_signals, priority_order=None):
        raise RuntimeError(f"boom-{self.personality}-{date}")


def test_multi_personality_shared_day_errors_count_once(monkeypatch):
    FakeBacktestEngine.instances = []
    shared_adapter = FakeSharedSignalAdapter()

    monkeypatch.setattr("backtest.multi_personality_engine.BacktestEngine", FailingBacktestEngine)
    monkeypatch.setattr(
        "backtest.multi_personality_engine.create_workflow_adapter",
        lambda **kwargs: shared_adapter,
    )

    backtest = MultiPersonalityBacktest(
        tickers=["AAA", "BBB"],
        start_date="2026-01-02",
        end_date="2026-01-05",
        personalities=["balanced"],
        use_llm=True,
        analysts=["fundamental"],
    )
    backtest.shared_cache = FakeSharedCache()

    comparison = backtest.run(prefetch=False, generate_report=False)

    result = comparison.personality_results["balanced"]
    assert result.error_count == 2
    assert len(result.result.errors) == 2


class ParallelProbeBacktestEngine(FakeBacktestEngine):
    barrier = None
    seen_scopes = []

    def _generate_llm_decisions_with_precollected_signals(self, date, prices, enhanced_signals, priority_order=None):
        from llm.inference import get_token_scope

        ParallelProbeBacktestEngine.seen_scopes.append(get_token_scope())
        if ParallelProbeBacktestEngine.barrier is not None:
            ParallelProbeBacktestEngine.barrier.wait(timeout=1.5)
        return super()._generate_llm_decisions_with_precollected_signals(
            date,
            prices,
            enhanced_signals,
            priority_order=priority_order,
        )


class SingleDaySharedCache(FakeSharedCache):
    def __init__(self):
        super().__init__()
        self._prices = {"2026-01-02": {"AAA": 100.0, "BBB": 200.0}}


class PrefetchProbeAdapter(FakeSharedSignalAdapter):
    def __init__(self):
        super().__init__()
        self.load_threads = []
        self.prefetch_started = threading.Event()

    def load_or_compute_shared_phase1(self, trading_date, prices, max_workers=5):
        self.load_threads.append((trading_date, threading.current_thread().name))
        if trading_date == "2026-01-05" and threading.current_thread() is not threading.main_thread():
            self.prefetch_started.set()
        return super().load_or_compute_shared_phase1(trading_date, prices, max_workers=max_workers)


class PrefetchFailureAdapter(PrefetchProbeAdapter):
    def __init__(self):
        super().__init__()
        self.failed_dates = set()

    def load_or_compute_shared_phase1(self, trading_date, prices, max_workers=5):
        self.load_threads.append((trading_date, threading.current_thread().name))
        if (
            trading_date == "2026-01-05"
            and threading.current_thread() is not threading.main_thread()
            and trading_date not in self.failed_dates
        ):
            self.failed_dates.add(trading_date)
            self.prefetch_started.set()
            raise RuntimeError("prefetch boom")
        if trading_date == "2026-01-05" and threading.current_thread() is not threading.main_thread():
            self.prefetch_started.set()
        return super().load_or_compute_shared_phase1(trading_date, prices, max_workers=max_workers)


class BlockingPhase2BacktestEngine(FakeBacktestEngine):
    block_event = None

    def _generate_llm_decisions_with_precollected_signals(self, date, prices, enhanced_signals, priority_order=None):
        if date == "2026-01-02" and BlockingPhase2BacktestEngine.block_event is not None:
            BlockingPhase2BacktestEngine.block_event.wait(timeout=1.5)
        return super()._generate_llm_decisions_with_precollected_signals(
            date,
            prices,
            enhanced_signals,
            priority_order=priority_order,
        )


class TimingPrefetchAdapter(FakeSharedSignalAdapter):
    def __init__(self, sync_delay=0.02, prefetch_delay=0.05):
        super().__init__()
        self.sync_delay = sync_delay
        self.prefetch_delay = prefetch_delay
        self.load_threads = []
        self.prefetch_started = threading.Event()

    def load_or_compute_shared_phase1(self, trading_date, prices, max_workers=5):
        self.load_threads.append((trading_date, threading.current_thread().name))
        if trading_date == "2026-01-02":
            time.sleep(self.sync_delay)
        elif trading_date == "2026-01-05":
            if threading.current_thread() is not threading.main_thread():
                self.prefetch_started.set()
            time.sleep(self.prefetch_delay)
        return super().load_or_compute_shared_phase1(trading_date, prices, max_workers=max_workers)


class OverlapPhase2BacktestEngine(FakeBacktestEngine):
    block_event = None
    overlap_delay = 0.08

    def _generate_llm_decisions_with_precollected_signals(self, date, prices, enhanced_signals, priority_order=None):
        if date == "2026-01-02" and OverlapPhase2BacktestEngine.block_event is not None:
            OverlapPhase2BacktestEngine.block_event.wait(timeout=1.5)
            time.sleep(self.overlap_delay)
        return super()._generate_llm_decisions_with_precollected_signals(
            date,
            prices,
            enhanced_signals,
            priority_order=priority_order,
        )


def test_multi_personality_phase2_runs_in_parallel_and_keeps_token_scopes(monkeypatch):
    FakeBacktestEngine.instances = []
    ParallelProbeBacktestEngine.seen_scopes = []
    ParallelProbeBacktestEngine.barrier = threading.Barrier(2)
    shared_adapter = FakeSharedSignalAdapter()

    monkeypatch.setattr("backtest.multi_personality_engine.BacktestEngine", ParallelProbeBacktestEngine)
    monkeypatch.setattr(
        "backtest.multi_personality_engine.create_workflow_adapter",
        lambda **kwargs: shared_adapter,
    )

    backtest = MultiPersonalityBacktest(
        tickers=["AAA", "BBB"],
        start_date="2026-01-02",
        end_date="2026-01-02",
        personalities=["balanced", "aggressive"],
        use_llm=True,
        analysts=["fundamental"],
        max_workers=2,
    )
    backtest.shared_cache = SingleDaySharedCache()

    comparison = backtest.run(prefetch=False, generate_report=False)

    assert comparison.personality_results["balanced"].error_count == 0
    assert comparison.personality_results["aggressive"].error_count == 0
    assert set(ParallelProbeBacktestEngine.seen_scopes) == {
        "personality:balanced",
        "personality:aggressive",
    }
    assert comparison.shared_data_stats["phase2_execution_mode"] == "parallel_threads"
    assert comparison.shared_data_stats["shared_phase1_token_usage"]["calls"] == 1
    assert comparison.personality_results["balanced"].token_usage["calls"] == 1
    assert comparison.personality_results["aggressive"].token_usage["calls"] == 1
    assert get_token_stats("personality:balanced")["calls"] == 1
    assert get_token_stats("personality:aggressive")["calls"] == 1


def test_shared_phase1_prefetch_prepares_next_day_in_background(monkeypatch):
    FakeBacktestEngine.instances = []
    shared_adapter = PrefetchProbeAdapter()
    BlockingPhase2BacktestEngine.block_event = shared_adapter.prefetch_started

    monkeypatch.setattr("backtest.multi_personality_engine.BacktestEngine", BlockingPhase2BacktestEngine)
    monkeypatch.setattr(
        "backtest.multi_personality_engine.create_workflow_adapter",
        lambda **kwargs: shared_adapter,
    )

    backtest = MultiPersonalityBacktest(
        tickers=["AAA", "BBB"],
        start_date="2026-01-02",
        end_date="2026-01-05",
        personalities=["balanced"],
        use_llm=True,
        analysts=["fundamental"],
        max_workers=1,
    )
    backtest.shared_cache = FakeSharedCache()

    comparison = backtest.run(prefetch=False, generate_report=False)

    assert comparison.shared_data_stats["shared_phase1_prefetch_submitted"] == 1
    assert comparison.shared_data_stats["shared_phase1_prefetch_hits"] == 1
    assert comparison.shared_data_stats["shared_phase1_prefetch_failures"] == 0
    assert comparison.shared_data_stats["shared_phase1_prefetch_compute_seconds"] >= 0.0
    assert comparison.shared_data_stats["shared_phase1_prefetch_wait_seconds"] >= 0.0
    assert comparison.shared_data_stats["shared_phase1_sync_load_seconds"] >= 0.0
    assert comparison.shared_data_stats["shared_phase1_prefetch_hit_rate"] == 1.0
    assert comparison.shared_data_stats["shared_phase1_pipeline_utilization"] >= 0.0
    assert (
        comparison.shared_data_stats["shared_phase1_prefetch_compute_seconds"]
        >= comparison.shared_data_stats["shared_phase1_prefetch_wait_seconds"]
    )
    day2_threads = [name for day, name in shared_adapter.load_threads if day == "2026-01-05"]
    assert day2_threads
    assert any(name != threading.main_thread().name for name in day2_threads)


def test_shared_phase1_prefetch_failure_falls_back_to_sync(monkeypatch):
    FakeBacktestEngine.instances = []
    shared_adapter = PrefetchFailureAdapter()
    BlockingPhase2BacktestEngine.block_event = shared_adapter.prefetch_started

    monkeypatch.setattr("backtest.multi_personality_engine.BacktestEngine", BlockingPhase2BacktestEngine)
    monkeypatch.setattr(
        "backtest.multi_personality_engine.create_workflow_adapter",
        lambda **kwargs: shared_adapter,
    )

    backtest = MultiPersonalityBacktest(
        tickers=["AAA", "BBB"],
        start_date="2026-01-02",
        end_date="2026-01-05",
        personalities=["balanced"],
        use_llm=True,
        analysts=["fundamental"],
        max_workers=1,
    )
    backtest.shared_cache = FakeSharedCache()

    comparison = backtest.run(prefetch=False, generate_report=False)

    assert comparison.personality_results["balanced"].error_count == 0
    assert comparison.shared_data_stats["shared_phase1_prefetch_submitted"] == 1
    assert comparison.shared_data_stats["shared_phase1_prefetch_hits"] == 0
    assert comparison.shared_data_stats["shared_phase1_prefetch_failures"] == 1
    assert comparison.shared_data_stats["shared_phase1_prefetch_wait_seconds"] >= 0.0
    assert comparison.shared_data_stats["shared_phase1_prefetch_hit_rate"] == 0.0
    assert comparison.shared_data_stats["shared_phase1_prefetch_fallback_sync_seconds"] > 0.0
    assert comparison.shared_data_stats["shared_phase1_sync_load_seconds"] >= (
        comparison.shared_data_stats["shared_phase1_prefetch_fallback_sync_seconds"]
    )
    day2_threads = [name for day, name in shared_adapter.load_threads if day == "2026-01-05"]
    assert any(name != threading.main_thread().name for name in day2_threads)
    assert any(name == threading.main_thread().name for name in day2_threads)


def test_shared_phase1_artifact_load_tolerates_missing_token_scope_module(monkeypatch):
    backtest = MultiPersonalityBacktest(
        tickers=["AAA", "BBB"],
        start_date="2026-01-02",
        end_date="2026-01-02",
        personalities=["balanced"],
        use_llm=True,
        analysts=["fundamental"],
        max_workers=1,
    )

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "llm.inference":
            raise ModuleNotFoundError("llm.inference unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    artifact, elapsed = backtest._load_shared_phase1_artifact(
        FakeSharedSignalAdapter(),
        "2026-01-02",
        {"AAA": 100.0, "BBB": 200.0},
        2,
    )

    assert artifact.metadata["cache_hit"] is False
    assert elapsed >= 0.0


def test_shared_phase1_timing_stats_capture_pipeline_overlap(monkeypatch):
    FakeBacktestEngine.instances = []
    shared_adapter = TimingPrefetchAdapter(sync_delay=0.02, prefetch_delay=0.05)
    OverlapPhase2BacktestEngine.block_event = shared_adapter.prefetch_started

    monkeypatch.setattr("backtest.multi_personality_engine.BacktestEngine", OverlapPhase2BacktestEngine)
    monkeypatch.setattr(
        "backtest.multi_personality_engine.create_workflow_adapter",
        lambda **kwargs: shared_adapter,
    )

    backtest = MultiPersonalityBacktest(
        tickers=["AAA", "BBB"],
        start_date="2026-01-02",
        end_date="2026-01-05",
        personalities=["balanced"],
        use_llm=True,
        analysts=["fundamental"],
        max_workers=1,
    )
    backtest.shared_cache = FakeSharedCache()

    comparison = backtest.run(prefetch=False, generate_report=False)
    stats = comparison.shared_data_stats

    assert stats["shared_phase1_sync_load_seconds"] >= 0.015
    assert stats["shared_phase1_prefetch_compute_seconds"] >= 0.045
    assert stats["shared_phase1_prefetch_wait_seconds"] < stats["shared_phase1_prefetch_compute_seconds"]
    assert stats["shared_phase1_pipeline_hidden_seconds"] > 0
    assert 0 < stats["shared_phase1_pipeline_utilization"] <= 1
    assert stats["shared_phase1_prefetch_hit_rate"] == 1.0


def test_shared_phase1_artifact_cache_hit_avoids_recompute(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_dir = Path(tmp_dir) / "cache"
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["AAA", "BBB"],
            initial_cash=100000.0,
            market="cn",
            analysts=["fundamental"],
            personality="balanced",
            db_path=str(db_path),
            llm_provider="test_provider",
            llm_model="test_model",
            shared_analyst_cache_dir=str(cache_dir),
            shared_phase1_cache_dir=str(cache_dir / "phase1_artifacts"),
        )
        prices = {"AAA": 100.0, "BBB": 200.0}
        calls = []

        def fake_collect(trading_date, price_map, max_workers=5):
            calls.append((trading_date, tuple(sorted(price_map)), max_workers))
            return {
                ticker: {
                    "ticker": ticker,
                    "analyst_signals": [f"signal-{ticker}-{trading_date}"],
                    "priority_score": 1.0,
                    "summary": {},
                }
                for ticker in price_map
            }

        monkeypatch.setattr(adapter, "collect_signals_only_parallel_v2", fake_collect)

        artifact_first = adapter.load_or_compute_shared_phase1("2026-01-02", prices, max_workers=2)
        artifact_second = adapter.load_or_compute_shared_phase1("2026-01-02", prices, max_workers=2)

        assert calls == [("2026-01-02", ("AAA", "BBB"), 2)]
        assert artifact_first.metadata["cache_hit"] is False
        assert artifact_second.metadata["cache_hit"] is True
        assert artifact_second.priority_order == artifact_first.priority_order
        assert artifact_second.enhanced_signals["AAA"]["analyst_signals"] == ["signal-AAA-2026-01-02"]

        adapter.close()


def test_shared_phase1_artifact_cache_key_or_version_change_invalidates(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_dir = Path(tmp_dir) / "cache"
        db_path = Path(tmp_dir) / "adapter.db"
        prices = {"AAA": 100.0, "BBB": 200.0}
        calls = []

        def fake_collect(trading_date, price_map, max_workers=5):
            calls.append((trading_date, tuple(sorted(price_map)), max_workers))
            return {
                ticker: {
                    "ticker": ticker,
                    "analyst_signals": [f"signal-{ticker}-{trading_date}"],
                    "priority_score": 1.0,
                    "summary": {},
                }
                for ticker in price_map
            }

        adapter_v1 = BacktestWorkflowAdapter(
            tickers=["AAA", "BBB"],
            initial_cash=100000.0,
            market="cn",
            analysts=["fundamental"],
            personality="balanced",
            db_path=str(db_path),
            llm_provider="test_provider",
            llm_model="test_model",
            shared_analyst_cache_dir=str(cache_dir),
            shared_phase1_cache_dir=str(cache_dir / "phase1_artifacts"),
        )
        monkeypatch.setattr(adapter_v1, "collect_signals_only_parallel_v2", fake_collect)
        artifact_v1 = adapter_v1.load_or_compute_shared_phase1("2026-01-02", prices, max_workers=2)
        assert artifact_v1.metadata["cache_hit"] is False
        adapter_v1.close()

        monkeypatch.setattr("backtest.workflow_adapter.SharedPhase1ArtifactCache.ARTIFACT_VERSION", "v3")
        monkeypatch.setattr("backtest.workflow_adapter.BacktestWorkflowAdapter.SHARED_PHASE1_ARTIFACT_VERSION", "v3")

        adapter_v2 = BacktestWorkflowAdapter(
            tickers=["AAA", "BBB"],
            initial_cash=100000.0,
            market="cn",
            analysts=["fundamental"],
            personality="balanced",
            db_path=str(db_path),
            llm_provider="test_provider",
            llm_model="test_model",
            shared_analyst_cache_dir=str(cache_dir),
            shared_phase1_cache_dir=str(cache_dir / "phase1_artifacts"),
        )
        monkeypatch.setattr(adapter_v2, "collect_signals_only_parallel_v2", fake_collect)
        artifact_v2 = adapter_v2.load_or_compute_shared_phase1("2026-01-02", prices, max_workers=2)

        assert len(calls) == 2
        assert artifact_v2.metadata["cache_hit"] is False
        assert artifact_v2.metadata["artifact_version"] == "v3"

        adapter_v2.close()


def test_shared_phase1_artifact_price_change_invalidates(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_dir = Path(tmp_dir) / "cache"
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["AAA", "BBB"],
            initial_cash=100000.0,
            market="cn",
            analysts=["fundamental"],
            personality="balanced",
            db_path=str(db_path),
            llm_provider="test_provider",
            llm_model="test_model",
            shared_analyst_cache_dir=str(cache_dir),
            shared_phase1_cache_dir=str(cache_dir / "phase1_artifacts"),
        )
        calls = []

        def fake_collect(trading_date, price_map, max_workers=5):
            calls.append((trading_date, dict(price_map)))
            return {
                ticker: {
                    "ticker": ticker,
                    "analyst_signals": [f"signal-{ticker}-{trading_date}-{price_map[ticker]}"],
                    "priority_score": 1.0,
                    "summary": {},
                }
                for ticker in price_map
            }

        monkeypatch.setattr(adapter, "collect_signals_only_parallel_v2", fake_collect)

        prices_v1 = {"AAA": 100.0, "BBB": 200.0}
        prices_v2 = {"AAA": 100.5, "BBB": 200.0}
        try:
            artifact_v1 = adapter.load_or_compute_shared_phase1("2026-01-02", prices_v1, max_workers=2)
            artifact_v2 = adapter.load_or_compute_shared_phase1("2026-01-02", prices_v2, max_workers=2)
        finally:
            adapter.close()

        assert artifact_v1.metadata["cache_hit"] is False
        assert artifact_v2.metadata["cache_hit"] is False
        assert len(calls) == 2
        assert artifact_v1.metadata["price_input_signature"] != artifact_v2.metadata["price_input_signature"]


def test_shared_phase1_artifact_load_failure_falls_back_to_recompute(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_dir = Path(tmp_dir) / "cache"
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["AAA", "BBB"],
            initial_cash=100000.0,
            market="cn",
            analysts=["fundamental"],
            personality="balanced",
            db_path=str(db_path),
            llm_provider="test_provider",
            llm_model="test_model",
            shared_analyst_cache_dir=str(cache_dir),
            shared_phase1_cache_dir=str(cache_dir / "phase1_artifacts"),
        )
        prices = {"AAA": 100.0, "BBB": 200.0}
        calls = []

        def fake_collect(trading_date, price_map, max_workers=5):
            calls.append((trading_date, tuple(sorted(price_map)), max_workers))
            return {
                ticker: {
                    "ticker": ticker,
                    "analyst_signals": [f"signal-{ticker}-{trading_date}-{len(calls)}"],
                    "priority_score": 1.0,
                    "summary": {},
                }
                for ticker in price_map
            }

        monkeypatch.setattr(adapter, "collect_signals_only_parallel_v2", fake_collect)
        first_artifact = adapter.load_or_compute_shared_phase1("2026-01-02", prices, max_workers=2)

        artifact_path = adapter.shared_phase1_artifact_cache._entry_path(
            trading_date="2026-01-02",
            market="cn",
            tickers=["AAA", "BBB"],
            analysts=["fundamental"],
            llm_provider="test_provider",
            llm_model="test_model",
            prices=prices,
            phase1_input_signature=first_artifact.metadata["phase1_input_signature"],
        )
        artifact_path.write_text("{broken json", encoding="utf-8")

        artifact = adapter.load_or_compute_shared_phase1("2026-01-02", prices, max_workers=2)

        assert len(calls) == 2
        assert artifact.metadata["cache_hit"] is False
        assert artifact.enhanced_signals["AAA"]["analyst_signals"] == ["signal-AAA-2026-01-02-2"]

        adapter.close()


def test_multi_personality_create_engines_passes_config_to_fof(monkeypatch):
    captured = []

    class _CapturedBacktestEngine(FakeBacktestEngine):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append((kwargs.get("personality"), kwargs.get("config")))

    class _CapturedFOFEngine(FakeBacktestEngine):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append((kwargs.get("personality"), kwargs.get("config")))

    monkeypatch.setattr("backtest.multi_personality_engine.BacktestEngine", _CapturedBacktestEngine)
    monkeypatch.setattr("backtest.multi_personality_engine.create_backtest_engine", _CapturedFOFEngine)

    config = {
        "market": "us",
        "llm": {"provider": "Ark", "model": "deepseek-v3.2"},
        "fof": {"sleeves": [{"personality": "balanced", "weight": 0.6}]},
    }
    backtest = MultiPersonalityBacktest(
        tickers=["MSFT", "NVDA"],
        start_date="2026-01-02",
        end_date="2026-01-05",
        personalities=["fof", "balanced"],
        market="us",
        config=config,
        use_llm=True,
        analysts=["fundamental"],
    )

    engines = backtest._create_personality_engines()

    assert set(engines.keys()) == {"fof", "balanced"}
    assert captured[0][0] == "fof"
    assert captured[0][1]["llm"]["provider"] == "Ark"
    assert captured[0][1]["fof"]["sleeves"][0]["personality"] == "balanced"
    assert captured[1][0] == "balanced"
    assert captured[1][1]["market"] == "us"



def test_run_single_personality_uses_create_backtest_engine_for_fof(monkeypatch):
    from backtest.multi_personality_engine import run_single_personality

    captured = {}

    class _Engine:
        def run(self, prefetch=False, generate_report=True, run_id=None):
            tracker = PortfolioTracker(initial_cash=100000.0)
            return BacktestResult(
                run_id=run_id or "mp_fof_test",
                start_date="2026-01-02",
                end_date="2026-01-05",
                tickers=["MSFT", "NVDA"],
                market="us",
                initial_cash=100000.0,
                tracker=tracker,
                metrics={},
                errors=[],
            )

        def close(self):
            return None

    def _fake_create_backtest_engine(**kwargs):
        captured.update(kwargs)
        return _Engine()

    monkeypatch.setattr("backtest.multi_personality_engine.create_backtest_engine", _fake_create_backtest_engine)

    result = run_single_personality(
        personality="fof",
        tickers=["MSFT", "NVDA"],
        start_date="2026-01-02",
        end_date="2026-01-05",
        initial_cash=100000.0,
        market="us",
        analysts=["fundamental"],
        db_path="data/signal_flux.db",
        shared_data_stats={},
        config={"llm": {"provider": "Ark"}, "fof": {"sleeves": [{"personality": "balanced", "weight": 1.0}]}},
        use_llm=True,
        shared_analyst_cache_dir="data/backtest/shared_analyst_cache/test",
    )

    assert captured["personality"] == "fof"
    assert captured["config"]["llm"]["provider"] == "Ark"
    assert captured["config"]["fof"]["sleeves"][0]["personality"] == "balanced"
    assert captured["use_llm"] is True
    assert result["personality"] == "fof"


def test_run_single_personality_prefers_generated_report_artifact_metrics(monkeypatch, tmp_path):
    from backtest.multi_personality_engine import run_single_personality

    monkeypatch.chdir(tmp_path)
    run_ids = []

    class _Engine:
        def run(self, prefetch=False, generate_report=True, run_id=None):
            run_ids.append(run_id)
            report_dir = Path("reports/backtest") / run_id
            report_dir.mkdir(parents=True)
            (report_dir / "metrics.json").write_text(
                json.dumps(
                    {
                        "metrics": {
                            "total_return": 7.5,
                            "max_drawdown": 1.2,
                            "sharpe_ratio": 0.8,
                            "total_trades": 4,
                            "win_rate": 75.0,
                            "avg_position_days": 3.0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            return BacktestResult(
                run_id=run_id or "mp_balanced_test",
                start_date="2026-01-02",
                end_date="2026-01-05",
                tickers=["MSFT"],
                market="us",
                initial_cash=100000.0,
                tracker=PortfolioTracker(initial_cash=100000.0),
                metrics={"total_return": -99.0},
                errors=[],
            )

        def close(self):
            return None

    monkeypatch.setattr("backtest.multi_personality_engine.create_backtest_engine", lambda **kwargs: _Engine())

    result = run_single_personality(
        personality="balanced",
        tickers=["MSFT"],
        start_date="2026-01-02",
        end_date="2026-01-05",
        initial_cash=100000.0,
        market="us",
        analysts=["fundamental"],
        db_path="data/signal_flux.db",
        shared_data_stats={},
        config={},
        use_llm=False,
    )

    assert run_ids and run_ids[0].startswith("mp_balanced_")
    assert result["total_return"] == 7.5
    assert result["max_drawdown"] == 1.2
    assert result["sharpe_ratio"] == 0.8
    assert result["trade_count"] == 4
    assert result["win_rate"] == 0.75
    assert result["avg_position_days"] == 3.0


def test_run_single_personality_falls_back_to_result_metrics_when_report_csv_is_bad(monkeypatch, tmp_path):
    from backtest.multi_personality_engine import run_single_personality

    monkeypatch.chdir(tmp_path)

    class _Engine:
        def run(self, prefetch=False, generate_report=True, run_id=None):
            report_dir = Path("reports/backtest") / run_id
            report_dir.mkdir(parents=True)
            (report_dir / "metrics.json").write_text(
                json.dumps(
                    {
                        "metrics": {
                            "total_return": 7.5,
                            "max_drawdown": 1.2,
                            "sharpe_ratio": 0.8,
                            "total_trades": 4,
                            "win_rate": 75.0,
                            "avg_position_days": 3.0,
                            "avg_turnover_ratio": 0.0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (report_dir / "trades.csv").write_text(
                "date,ticker,action,shares,price,value,justification\n"
                "2026-01-02,MSFT,BUY,1,100.0,bad,\n",
                encoding="utf-8",
            )
            (report_dir / "equity_curve.csv").write_text(
                "date,total_value,daily_return,cashflow\n"
                "2026-01-02,bad,0.0,90000.0\n",
                encoding="utf-8",
            )
            tracker = PortfolioTracker(initial_cash=100000.0)
            return BacktestResult(
                run_id=run_id or "mp_balanced_test",
                start_date="2026-01-02",
                end_date="2026-01-05",
                tickers=["MSFT"],
                market="us",
                initial_cash=100000.0,
                tracker=tracker,
                metrics={
                    "total_return": 1.5,
                    "max_drawdown": 0.2,
                    "sharpe_ratio": 0.4,
                    "total_trades": 2,
                    "win_rate": 50.0,
                    "avg_position_days": 0.0,
                },
                errors=[],
            )

        def close(self):
            return None

    monkeypatch.setattr("backtest.multi_personality_engine.create_backtest_engine", lambda **kwargs: _Engine())

    result = run_single_personality(
        personality="balanced",
        tickers=["MSFT"],
        start_date="2026-01-02",
        end_date="2026-01-05",
        initial_cash=100000.0,
        market="us",
        analysts=["fundamental"],
        db_path="data/signal_flux.db",
        shared_data_stats={},
        config={},
        use_llm=False,
    )

    assert result["total_return"] == 1.5
    assert result["max_drawdown"] == 0.2
    assert result["sharpe_ratio"] == 0.4
    assert result["trade_count"] == 2
    assert result["win_rate"] == 0.5
