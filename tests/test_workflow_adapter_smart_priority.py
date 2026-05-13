"""Tests for smart-priority workflow adapter lock/concurrency fixes."""

from datetime import datetime
from pathlib import Path
import sys
import tempfile
import types

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for extra_path in reversed((
    PROJECT_ROOT,
    PROJECT_ROOT / "deepfund" / "src",
    PROJECT_ROOT / "deepear" / "src",
)):
    extra_path_str = str(extra_path)
    if extra_path_str not in sys.path:
        sys.path.insert(0, extra_path_str)

try:
    import rank_bm25  # noqa: F401
except ModuleNotFoundError:
    rank_bm25_stub = types.ModuleType("rank_bm25")

    class BM25Okapi:  # pragma: no cover - test import shim only
        def __init__(self, *args, **kwargs):
            pass

        def get_scores(self, *args, **kwargs):
            return []

    rank_bm25_stub.BM25Okapi = BM25Okapi
    sys.modules["rank_bm25"] = rank_bm25_stub

try:
    import sentence_transformers  # noqa: F401
except ModuleNotFoundError:
    sentence_transformers_stub = types.ModuleType("sentence_transformers")

    class SentenceTransformer:  # pragma: no cover - test import shim only
        def __init__(self, *args, **kwargs):
            pass

        def encode(self, *args, **kwargs):
            return []

    sentence_transformers_stub.SentenceTransformer = SentenceTransformer
    sys.modules["sentence_transformers"] = sentence_transformers_stub

from backtest.workflow_adapter import BacktestWorkflowAdapter
from backtest.engine import BacktestEngine
from deepfund.src.graph.constants import Action, AgentKey, Signal
from deepfund.src.graph.schema import AnalystSignal, Decision


def _install_agent_registry_stub(monkeypatch):
    agents_pkg = sys.modules.get("agents")
    if agents_pkg is None:
        agents_pkg = types.ModuleType("agents")
        monkeypatch.setitem(sys.modules, "agents", agents_pkg)

    registry_stub = types.ModuleType("agents.registry")

    class AgentRegistry:
        @classmethod
        def check_agent_key(cls, key):
            return False

        @classmethod
        def get_agent_func_by_key(cls, key):
            return None

    registry_stub.AgentRegistry = AgentRegistry
    monkeypatch.setitem(sys.modules, "agents.registry", registry_stub)
    monkeypatch.setattr(agents_pkg, "registry", registry_stub, raising=False)
    return AgentRegistry


def test_backtest_engine_passes_db_path_to_workflow_adapter(monkeypatch):
    captured = {}

    def fake_create_workflow_adapter(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("backtest.engine.create_workflow_adapter", fake_create_workflow_adapter)

    engine = BacktestEngine(
        tickers=["AAA"],
        start_date="2026-01-02",
        end_date="2026-01-03",
        db_path="/tmp/custom-backtest.db",
        use_llm=True,
        analysts=["fundamental"],
        personality="balanced",
    )

    assert captured["db_path"] == "/tmp/custom-backtest.db"
    assert engine.workflow_adapter is not None


def test_create_temp_db_path_is_unique_when_called_rapidly():
    """Temp DB path should be unique even when created within the same second."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["TEST"],
            initial_cash=100000.0,
            db_path=str(db_path),
        )
        try:
            generated = [adapter._create_temp_db() for _ in range(50)]
            assert len(generated) == len(set(generated))
        finally:
            adapter.close()


def test_phase1_signal_collection_runs_analysts_only(monkeypatch):
    AgentRegistry = _install_agent_registry_stub(monkeypatch)
    """Signal-only phase should not invoke portfolio manager."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
            analysts=["fundamental", "technical"],
        )

        state_skip_flags = []

        def fundamental_agent(state):
            state_skip_flags.append(state.get("skip_db_writes", False))
            return {
                "analyst_signals": [
                    AnalystSignal(signal=Signal.BULLISH, justification="fundamental")
                ]
            }

        def technical_agent(state):
            state_skip_flags.append(state.get("skip_db_writes", False))
            return {
                "analyst_signals": [
                    AnalystSignal(signal=Signal.BEARISH, justification="technical")
                ]
            }

        def fake_check_agent_key(cls, key):
            return key in {"fundamental", "technical"}

        def fake_get_agent_func(cls, key):
            if key == "fundamental":
                return fundamental_agent
            if key == "technical":
                return technical_agent
            if key == AgentKey.PORTFOLIO:
                raise AssertionError("Portfolio manager should not run during phase1 collection")
            return None

        monkeypatch.setattr(AgentRegistry, "check_agent_key", classmethod(fake_check_agent_key))
        monkeypatch.setattr(AgentRegistry, "get_agent_func_by_key", classmethod(fake_get_agent_func))

        config = {
            "llm": {"provider": "test", "model": "test-model"},
            "tickers": ["AAA"],
            "exp_name": "test_exp",
            "workflow_analysts": ["fundamental", "technical"],
        }
        portfolio_dict = {
            "id": "p1",
            "cashflow": 100000.0,
            "positions": {"AAA": {"shares": 0, "value": 0.0}},
        }

        try:
            result = adapter._process_single_ticker_for_signals_v2(
                ticker="AAA",
                trading_date="2026-01-02",
                trading_date_dt=datetime(2026, 1, 2),
                price=100.0,
                config=config,
                portfolio_dict=portfolio_dict,
            )
            assert len(result["analyst_signals"]) == 2
            assert all(state_skip_flags)
        finally:
            adapter.close()


def test_phase2_uses_precollected_signals_without_rerunning_analysts(monkeypatch):
    AgentRegistry = _install_agent_registry_stub(monkeypatch)
    """Decision phase should call only portfolio manager with pre-collected signals."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["AAA", "BBB"],
            initial_cash=100000.0,
            db_path=str(db_path),
            analysts=["fundamental", "technical"],
        )

        pre_collected = {
            "AAA": {
                "ticker": "AAA",
                "analyst_signals": [AnalystSignal(signal=Signal.BULLISH, justification="a")],
                "priority_score": 0.9,
                "summary": {},
            },
            "BBB": {
                "ticker": "BBB",
                "analyst_signals": [AnalystSignal(signal=Signal.NEUTRAL, justification="b")],
                "priority_score": 0.5,
                "summary": {},
            },
        }
        monkeypatch.setattr(
            adapter,
            "collect_signals_only_parallel_v2",
            lambda trading_date, prices, max_workers: pre_collected,
        )
        monkeypatch.setattr(adapter, "_get_smart_priority_order", lambda signals: ["AAA", "BBB"])

        received = []

        def fake_portfolio_agent(state):
            received.append((state["ticker"], state["analyst_signals"]))
            return {
                "decision": Decision(
                    action=Action.HOLD,
                    shares=0,
                    price=100.0,
                    justification="mock",
                )
            }

        def fake_get_agent_func(cls, key):
            if key == AgentKey.PORTFOLIO:
                return fake_portfolio_agent
            raise AssertionError(f"Unexpected agent request in phase2: {key}")

        monkeypatch.setattr(AgentRegistry, "get_agent_func_by_key", classmethod(fake_get_agent_func))

        try:
            decisions = adapter.run_single_day_with_smart_priority(
                trading_date="2026-01-02",
                prices={"AAA": 100.0, "BBB": 200.0},
                max_workers=2,
            )
            assert set(decisions.keys()) == {"AAA", "BBB"}
            assert [ticker for ticker, _ in received] == ["AAA", "BBB"]
            assert [signal.model_dump() for signal in received[0][1]] == [
                signal.model_dump() for signal in pre_collected["AAA"]["analyst_signals"]
            ]
            assert [signal.model_dump() for signal in received[1][1]] == [
                signal.model_dump() for signal in pre_collected["BBB"]["analyst_signals"]
            ]
        finally:
            adapter.close()


def test_normalize_decision_for_portfolio_clamps_to_executable_shares():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
        )

        from deepfund.src.graph.constants import Action as DecisionAction
        from deepfund.src.graph.schema import Decision, Portfolio, Position

        portfolio = Portfolio(
            id="p1",
            cashflow=1000.0,
            positions={"AAA": Position(shares=3, value=300.0)},
        )

        try:
            buy = adapter._normalize_decision_for_portfolio(
                portfolio,
                "AAA",
                Decision(action=DecisionAction.BUY, shares=1000, price=250.0, justification="buy too much"),
            )
            sell = adapter._normalize_decision_for_portfolio(
                portfolio,
                "AAA",
                Decision(action=DecisionAction.SELL, shares=999, price=250.0, justification="sell too much"),
            )

            assert buy.action == DecisionAction.BUY
            assert buy.shares == 4
            assert sell.action == DecisionAction.SELL
            assert sell.shares == 3
        finally:
            adapter.close()


def test_phase2_logs_and_returns_normalized_shares(monkeypatch):
    AgentRegistry = _install_agent_registry_stub(monkeypatch)
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["AAA", "BBB"],
            initial_cash=100000.0,
            db_path=str(db_path),
            analysts=["fundamental"],
        )

        pre_collected = {
            "AAA": {
                "ticker": "AAA",
                "analyst_signals": [AnalystSignal(signal=Signal.BULLISH, justification="a")],
                "priority_score": 0.9,
                "summary": {},
            },
            "BBB": {
                "ticker": "BBB",
                "analyst_signals": [AnalystSignal(signal=Signal.BULLISH, justification="b")],
                "priority_score": 0.8,
                "summary": {},
            },
        }

        decisions_by_ticker = {
            "AAA": Decision(action=Action.BUY, shares=1000, price=100.0, justification="oversized buy"),
            "BBB": Decision(action=Action.SELL, shares=999, price=50.0, justification="oversized sell"),
        }
        logged_messages = []

        def fake_portfolio_agent(state):
            return {"decision": decisions_by_ticker[state["ticker"]]}

        def fake_get_agent_func(cls, key):
            if key == AgentKey.PORTFOLIO:
                return fake_portfolio_agent
            raise AssertionError(f"Unexpected agent request in phase2: {key}")

        monkeypatch.setattr(AgentRegistry, "get_agent_func_by_key", classmethod(fake_get_agent_func))
        monkeypatch.setattr(
            'backtest.workflow_adapter.logger.info',
            lambda message: logged_messages.append(str(message)),
        )

        adapter.current_portfolio["cashflow"] = 1000.0
        adapter.current_portfolio["positions"] = {
            "AAA": {"shares": 0, "value": 0.0},
            "BBB": {"shares": 5, "value": 250.0},
        }

        try:
            decisions = adapter.run_single_day_with_precollected_signals(
                trading_date="2026-01-02",
                prices={"AAA": 100.0, "BBB": 50.0},
                enhanced_signals=pre_collected,
                priority_order=["AAA", "BBB"],
            )

            assert decisions["AAA"].action == "Buy"
            assert decisions["AAA"].shares == 10
            assert decisions["BBB"].action == "Sell"
            assert decisions["BBB"].shares == 5
            assert any("AAA: Buy 10 shares" in msg for msg in logged_messages)
            assert any("BBB: Sell 5 shares" in msg for msg in logged_messages)
            assert not any("AAA: Buy 1000 shares" in msg for msg in logged_messages)
            assert not any("BBB: Sell 999 shares" in msg for msg in logged_messages)
            assert adapter.current_portfolio["cashflow"] == 250.0
            assert adapter.current_portfolio["positions"]["AAA"]["shares"] == 10
            assert adapter.current_portfolio["positions"]["BBB"]["shares"] == 0
        finally:
            adapter.close()


def test_shared_analyst_cache_reuses_signals_across_personalities(monkeypatch):
    AgentRegistry = _install_agent_registry_stub(monkeypatch)
    """Signal collection should reuse cached analyst results across adapters."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        cache_dir = Path(tmp_dir) / "shared_cache"
        call_counts = {"fundamental": 0, "technical": 0}

        def fundamental_agent(state):
            call_counts["fundamental"] += 1
            return {
                "analyst_signals": [
                    AnalystSignal(signal=Signal.BULLISH, justification="fundamental cached")
                ]
            }

        def technical_agent(state):
            call_counts["technical"] += 1
            return {
                "analyst_signals": [
                    AnalystSignal(signal=Signal.NEUTRAL, justification="technical cached")
                ]
            }

        def fake_check_agent_key(cls, key):
            return key in {"fundamental", "technical"}

        def fake_get_agent_func(cls, key):
            if key == "fundamental":
                return fundamental_agent
            if key == "technical":
                return technical_agent
            return None

        monkeypatch.setattr(AgentRegistry, "check_agent_key", classmethod(fake_check_agent_key))
        monkeypatch.setattr(AgentRegistry, "get_agent_func_by_key", classmethod(fake_get_agent_func))

        config = {
            "llm": {"provider": "test", "model": "test-model"},
            "tickers": ["AAA"],
            "exp_name": "test_exp",
            "workflow_analysts": ["fundamental", "technical"],
        }
        portfolio_dict = {
            "id": "p1",
            "cashflow": 100000.0,
            "positions": {"AAA": {"shares": 0, "value": 0.0}},
        }

        adapter_one = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
            analysts=["fundamental", "technical"],
            personality="balanced",
            shared_analyst_cache_dir=str(cache_dir),
        )
        adapter_two = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
            analysts=["fundamental", "technical"],
            personality="aggressive",
            shared_analyst_cache_dir=str(cache_dir),
        )

        try:
            first = adapter_one._process_single_ticker_for_signals_v2(
                ticker="AAA",
                trading_date="2026-01-02",
                trading_date_dt=datetime(2026, 1, 2),
                price=100.0,
                config=config,
                portfolio_dict=portfolio_dict,
            )
            second = adapter_two._process_single_ticker_for_signals_v2(
                ticker="AAA",
                trading_date="2026-01-02",
                trading_date_dt=datetime(2026, 1, 2),
                price=100.0,
                config=config,
                portfolio_dict=portfolio_dict,
            )

            assert len(first["analyst_signals"]) == 2
            assert len(second["analyst_signals"]) == 2
            assert call_counts == {"fundamental": 1, "technical": 1}
        finally:
            adapter_one.close()
            adapter_two.close()


def test_shared_analyst_cache_skips_error_signals(monkeypatch):
    AgentRegistry = _install_agent_registry_stub(monkeypatch)
    """Error fallback signals should not be persisted into shared cache."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        cache_dir = Path(tmp_dir) / "shared_cache"
        call_count = {"fundamental": 0}

        def failing_agent(state):
            call_count["fundamental"] += 1
            return {
                "analyst_signals": [
                    AnalystSignal(signal=Signal.NEUTRAL, justification="[Error] transient failure")
                ]
            }

        def fake_check_agent_key(cls, key):
            return key == "fundamental"

        def fake_get_agent_func(cls, key):
            if key == "fundamental":
                return failing_agent
            return None

        monkeypatch.setattr(AgentRegistry, "check_agent_key", classmethod(fake_check_agent_key))
        monkeypatch.setattr(AgentRegistry, "get_agent_func_by_key", classmethod(fake_get_agent_func))

        config = {
            "llm": {"provider": "test", "model": "test-model"},
            "tickers": ["AAA"],
            "exp_name": "test_exp",
            "workflow_analysts": ["fundamental"],
        }
        portfolio_dict = {
            "id": "p1",
            "cashflow": 100000.0,
            "positions": {"AAA": {"shares": 0, "value": 0.0}},
        }

        adapter_one = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
            analysts=["fundamental"],
            shared_analyst_cache_dir=str(cache_dir),
        )
        adapter_two = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
            analysts=["fundamental"],
            shared_analyst_cache_dir=str(cache_dir),
        )

        try:
            adapter_one._process_single_ticker_for_signals_v2(
                ticker="AAA",
                trading_date="2026-01-02",
                trading_date_dt=datetime(2026, 1, 2),
                price=100.0,
                config=config,
                portfolio_dict=portfolio_dict,
            )
            adapter_two._process_single_ticker_for_signals_v2(
                ticker="AAA",
                trading_date="2026-01-02",
                trading_date_dt=datetime(2026, 1, 2),
                price=100.0,
                config=config,
                portfolio_dict=portfolio_dict,
            )

            assert call_count["fundamental"] == 2
        finally:
            adapter_one.close()
            adapter_two.close()


def test_shared_analyst_cache_save_failure_does_not_change_signals(monkeypatch):
    AgentRegistry = _install_agent_registry_stub(monkeypatch)
    """Cache write failures should not be treated as analyst failures."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        cache_dir = Path(tmp_dir) / "shared_cache"

        def fundamental_agent(state):
            return {
                "analyst_signals": [
                    AnalystSignal(signal=Signal.BULLISH, justification="fundamental cached")
                ]
            }

        def fake_check_agent_key(cls, key):
            return key == "fundamental"

        def fake_get_agent_func(cls, key):
            if key == "fundamental":
                return fundamental_agent
            return None

        monkeypatch.setattr(AgentRegistry, "check_agent_key", classmethod(fake_check_agent_key))
        monkeypatch.setattr(AgentRegistry, "get_agent_func_by_key", classmethod(fake_get_agent_func))

        config = {
            "llm": {"provider": "test", "model": "test-model"},
            "tickers": ["AAA"],
            "exp_name": "test_exp",
            "workflow_analysts": ["fundamental"],
        }
        portfolio_dict = {
            "id": "p1",
            "cashflow": 100000.0,
            "positions": {"AAA": {"shares": 0, "value": 0.0}},
        }

        adapter = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
            analysts=["fundamental"],
            shared_analyst_cache_dir=str(cache_dir),
        )

        try:
            monkeypatch.setattr(
                adapter.shared_analyst_cache,
                "save",
                lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
            )

            result = adapter._process_single_ticker_for_signals_v2(
                ticker="AAA",
                trading_date="2026-01-02",
                trading_date_dt=datetime(2026, 1, 2),
                price=100.0,
                config=config,
                portfolio_dict=portfolio_dict,
            )

            assert len(result["analyst_signals"]) == 1
            assert result["analyst_signals"][0].signal == Signal.BULLISH
            assert result["analyst_signals"][0].justification == "fundamental cached"
        finally:
            adapter.close()


def test_adapter_exp_name_isolated_across_personalities():
    """Adapters sharing a DB should still keep per-personality config isolated."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        balanced = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
            personality="balanced",
        )
        aggressive = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
            personality="aggressive",
        )

        try:
            assert balanced.run_id != aggressive.run_id
            assert balanced.exp_name != aggressive.exp_name
            assert balanced.config_id != aggressive.config_id
        finally:
            balanced.close()
            aggressive.close()


def test_base_analyst_uses_prefetched_input_without_fetch(monkeypatch):
    import importlib.util

    base_path = PROJECT_ROOT / "deepfund" / "src" / "agents" / "analysts" / "base.py"
    spec = importlib.util.spec_from_file_location("test_base_analyst_module", base_path)
    base_module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(base_module)
    BaseAnalyst = base_module.BaseAnalyst

    class DummyAnalyst(BaseAnalyst):
        def __init__(self):
            super().__init__("company_news", "{news}")

        def fetch_data(self, state, router):
            raise AssertionError("prefetched input should bypass fetch_data")

        def build_prompt(self, data):
            return "|".join(data)

    def fake_agent_call(prompt, llm_config, pydantic_model, agent_name):
        return AnalystSignal(signal=Signal.BULLISH, justification=prompt)

    monkeypatch.setattr(base_module, "agent_call", fake_agent_call)
    monkeypatch.setattr(base_module, "Router", lambda api_source: object())

    portfolio = type("PortfolioStub", (), {"id": "p1"})()
    analyst = DummyAnalyst()
    result = analyst.analyze(
        {
            "ticker": "AAA",
            "llm_config": {"provider": "test", "model": "test-model"},
            "portfolio": portfolio,
            "market": "cn",
            "skip_db_writes": True,
            "prefetched_analyst_data": {
                "company_news": {
                    "prompt_data": ["prefetched-news"],
                }
            },
        }
    )

    assert result["analyst_signals"][0].justification == "prefetched-news"



def test_shared_phase1_reuses_prefetched_company_news_payload_for_execution(monkeypatch):
    AgentRegistry = _install_agent_registry_stub(monkeypatch)
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        cache_dir = Path(tmp_dir) / "shared_cache"
        payload_calls = []

        def company_news_agent(state):
            payload = state["prefetched_analyst_data"]["company_news"]
            return {
                "analyst_signals": [
                    AnalystSignal(
                        signal=Signal.BULLISH,
                        justification=payload["prompt_data"][0],
                    )
                ]
            }

        def fake_check_agent_key(cls, key):
            return key == "company_news"

        def fake_get_agent_func(cls, key):
            if key == "company_news":
                return company_news_agent
            return None

        def fake_news_payload(self, trading_date, ticker):
            payload_calls.append((trading_date, ticker))
            return {
                "ticker": ticker,
                "trading_date": trading_date,
                "count": 1,
                "items": [],
                "prompt_data": [f"prompt-{ticker}"],
                "signature": f"news-{ticker}",
            }

        monkeypatch.setattr(AgentRegistry, "check_agent_key", classmethod(fake_check_agent_key))
        monkeypatch.setattr(AgentRegistry, "get_agent_func_by_key", classmethod(fake_get_agent_func))
        monkeypatch.setattr(BacktestWorkflowAdapter, "_get_company_news_signature_payload", fake_news_payload)

        adapter = BacktestWorkflowAdapter(
            tickers=["AAA", "BBB"],
            initial_cash=100000.0,
            market="cn",
            analysts=["company_news"],
            personality="balanced",
            db_path=str(db_path),
            llm_provider="test_provider",
            llm_model="test_model",
            shared_analyst_cache_dir=str(cache_dir),
            shared_phase1_cache_dir=str(cache_dir / "phase1_artifacts"),
        )

        try:
            artifact = adapter.load_or_compute_shared_phase1(
                "2026-01-02",
                {"AAA": 100.0, "BBB": 200.0},
                max_workers=2,
            )
        finally:
            adapter.close()

        assert sorted(payload_calls) == [("2026-01-02", "AAA"), ("2026-01-02", "BBB")]
        assert artifact.enhanced_signals["AAA"]["analyst_signals"][0].justification == "prompt-AAA"
        assert artifact.enhanced_signals["BBB"]["analyst_signals"][0].justification == "prompt-BBB"



def test_shared_analyst_cache_invalidates_company_news_on_input_signature_change(monkeypatch):
    AgentRegistry = _install_agent_registry_stub(monkeypatch)
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        cache_dir = Path(tmp_dir) / "shared_cache"
        call_count = {"company_news": 0}
        current_news_signature = {"AAA": "news-v1"}

        def company_news_agent(state):
            call_count["company_news"] += 1
            ticker = state["ticker"]
            return {
                "analyst_signals": [
                    AnalystSignal(
                        signal=Signal.BULLISH,
                        justification=f"company_news:{current_news_signature[ticker]}",
                    )
                ]
            }

        def fake_check_agent_key(cls, key):
            return key == "company_news"

        def fake_get_agent_func(cls, key):
            if key == "company_news":
                return company_news_agent
            return None

        def fake_news_signature(self, trading_date, ticker):
            return {
                "ticker": ticker,
                "trading_date": trading_date,
                "count": 1,
                "items": [],
                "signature": current_news_signature[ticker],
            }

        monkeypatch.setattr(AgentRegistry, "check_agent_key", classmethod(fake_check_agent_key))
        monkeypatch.setattr(AgentRegistry, "get_agent_func_by_key", classmethod(fake_get_agent_func))
        monkeypatch.setattr(BacktestWorkflowAdapter, "_get_company_news_signature_payload", fake_news_signature)

        config = {
            "llm": {"provider": "test", "model": "test-model"},
            "tickers": ["AAA"],
            "exp_name": "test_exp",
            "workflow_analysts": ["company_news"],
        }
        portfolio_dict = {
            "id": "p1",
            "cashflow": 100000.0,
            "positions": {"AAA": {"shares": 0, "value": 0.0}},
        }

        adapter_one = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
            analysts=["company_news"],
            shared_analyst_cache_dir=str(cache_dir),
        )
        adapter_two = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
            analysts=["company_news"],
            shared_analyst_cache_dir=str(cache_dir),
        )
        adapter_three = BacktestWorkflowAdapter(
            tickers=["AAA"],
            initial_cash=100000.0,
            db_path=str(db_path),
            analysts=["company_news"],
            shared_analyst_cache_dir=str(cache_dir),
        )

        try:
            first = adapter_one._process_single_ticker_for_signals_v2(
                ticker="AAA",
                trading_date="2026-01-02",
                trading_date_dt=datetime(2026, 1, 2),
                price=100.0,
                config=config,
                portfolio_dict=portfolio_dict,
            )

            current_news_signature["AAA"] = "news-v2"
            second = adapter_two._process_single_ticker_for_signals_v2(
                ticker="AAA",
                trading_date="2026-01-02",
                trading_date_dt=datetime(2026, 1, 2),
                price=100.0,
                config=config,
                portfolio_dict=portfolio_dict,
            )

            third = adapter_three._process_single_ticker_for_signals_v2(
                ticker="AAA",
                trading_date="2026-01-02",
                trading_date_dt=datetime(2026, 1, 2),
                price=100.0,
                config=config,
                portfolio_dict=portfolio_dict,
            )

            assert call_count == {"company_news": 2}
            assert first["analyst_signals"][0].justification == "company_news:news-v1"
            assert second["analyst_signals"][0].justification == "company_news:news-v2"
            assert third["analyst_signals"][0].justification == "company_news:news-v2"
        finally:
            adapter_one.close()
            adapter_two.close()
            adapter_three.close()



def test_shared_phase1_artifact_news_change_invalidates(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_dir = Path(tmp_dir) / "cache"
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["AAA", "BBB"],
            initial_cash=100000.0,
            market="cn",
            analysts=["company_news"],
            personality="balanced",
            db_path=str(db_path),
            llm_provider="test_provider",
            llm_model="test_model",
            shared_analyst_cache_dir=str(cache_dir),
            shared_phase1_cache_dir=str(cache_dir / "phase1_artifacts"),
        )
        calls = []
        current_news_signature = {"AAA": "news-v1", "BBB": "news-v1"}

        def fake_collect(trading_date, price_map, max_workers=5, prefetched_analyst_inputs=None):
            calls.append((trading_date, dict(price_map)))
            return {
                ticker: {
                    "ticker": ticker,
                    "analyst_signals": [f"signal-{ticker}-{trading_date}-{current_news_signature[ticker]}"],
                    "priority_score": 1.0,
                    "summary": {},
                }
                for ticker in price_map
            }

        def fake_news_signature(self, trading_date, ticker):
            return {
                "ticker": ticker,
                "trading_date": trading_date,
                "count": 1,
                "items": [],
                "signature": current_news_signature[ticker],
            }

        monkeypatch.setattr(adapter, "collect_signals_only_parallel_v2", fake_collect)
        monkeypatch.setattr(BacktestWorkflowAdapter, "_get_company_news_signature_payload", fake_news_signature)

        prices = {"AAA": 100.0, "BBB": 200.0}
        try:
            artifact_v1 = adapter.load_or_compute_shared_phase1("2026-01-02", prices, max_workers=2)
            current_news_signature["AAA"] = "news-v2"
            artifact_v2 = adapter.load_or_compute_shared_phase1("2026-01-02", prices, max_workers=2)
            artifact_v3 = adapter.load_or_compute_shared_phase1("2026-01-02", prices, max_workers=2)
        finally:
            adapter.close()

        assert len(calls) == 2
        assert artifact_v1.metadata["cache_hit"] is False
        assert artifact_v2.metadata["cache_hit"] is False
        assert artifact_v3.metadata["cache_hit"] is True
        assert artifact_v1.metadata["news_input_signature"] != artifact_v2.metadata["news_input_signature"]
        assert artifact_v1.metadata["phase1_input_signature"] != artifact_v2.metadata["phase1_input_signature"]
        assert artifact_v2.metadata["news_input_signatures_by_ticker"]["AAA"] == "news-v2"
