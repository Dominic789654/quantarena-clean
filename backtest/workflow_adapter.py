"""
Backtest Workflow Adapter
=========================

Adapter to integrate DeepFund's AgentWorkflow into the backtest framework.
Provides simplified interface for sequential day-by-day trading simulation.
"""

import os
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from loguru import logger

# Setup project paths using unified path manager
from shared.utils.path_manager import setup_paths, get_project_root
setup_paths()
from shared.config.profile_registry import PROFILE_ALIASES, normalize_profile_name

from dotenv import load_dotenv

# Load environment
load_dotenv(get_project_root() / ".env")


# Re-import block: these four classes used to be defined directly in this
# file. They now live in backtest/workflow/ (see
# docs/refactor_program_plan.md Phase 3); re-importing here keeps every
# existing `from backtest.workflow_adapter import <Name>` import and
# `monkeypatch.setattr("backtest.workflow_adapter.<Name>.<attr>", ...)`
# string path resolving against the same class objects.
from backtest.workflow.decisions import BacktestDecision  # noqa: F401
from backtest.workflow.phase1_artifact import (  # noqa: F401
    SharedPhase1Artifact,
    SharedPhase1ArtifactCache,
)
from backtest.workflow.signal_cache import SharedAnalystSignalCache  # noqa: F401
from backtest.workflow import (
    scoring,
    decision_apply,
    db_store,
    company_news_signature,
    signal_collection,
    phase1_pipeline,
)


class BacktestWorkflowAdapter:
    """
    Adapter to run DeepFund's AgentWorkflow in a backtest context.

    Key differences from live trading:
    1. Uses isolated SQLite database for each backtest run
    2. Manages portfolio state internally (no external persistence)
    3. Simplified config management
    """

    # Default analysts for backtest
    DEFAULT_ANALYSTS = ["fundamental", "technical", "company_news"]
    SHARED_PHASE1_ARTIFACT_VERSION = SharedPhase1ArtifactCache.ARTIFACT_VERSION

    # Supported profiles (including legacy personality aliases accepted by CLI)
    PERSONALITY_ALIASES = dict(PROFILE_ALIASES)
    PERSONALITIES = list(PERSONALITY_ALIASES.keys())

    @classmethod
    def _normalize_personality(cls, personality: Optional[str]) -> str:
        """Normalize personality/profile aliases to canonical names."""
        return normalize_profile_name(personality)

    def __init__(
        self,
        tickers: List[str],
        initial_cash: float,
        market: str = "cn",
        analysts: Optional[List[str]] = None,
        personality: str = "balanced",
        db_path: Optional[str] = None,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        api_source_config: Optional[Dict[str, str]] = None,
        shared_analyst_cache_dir: Optional[str] = None,
        shared_phase1_cache_dir: Optional[str] = None,
    ):
        """
        Initialize the backtest workflow adapter.

        Args:
            tickers: List of ticker symbols
            initial_cash: Starting capital
            market: Market type ("cn" or "us")
            analysts: List of analysts to use (default: fundamental, technical, company_news)
            personality: Investment personality
            db_path: Path to SQLite database (default: temp file for each run)
            llm_provider: LLM provider name (default: from env REASONING_MODEL_PROVIDER)
            llm_model: LLM model name (default: from env REASONING_MODEL_ID)
        """
        self.tickers = tickers
        self.initial_cash = initial_cash
        self.market = market.lower()
        self.analysts = analysts or self.DEFAULT_ANALYSTS
        self.personality = self._normalize_personality(personality)
        # Read from env vars or use defaults
        self.llm_provider = llm_provider or os.getenv("REASONING_MODEL_PROVIDER", "DeepSeek")
        self.llm_model = llm_model or os.getenv("REASONING_MODEL_ID", "deepseek-v4-flash")
        self.api_source = self._build_api_source_config(api_source_config)
        self.shared_analyst_cache = None
        phase1_cache_root = None
        if shared_phase1_cache_dir:
            phase1_cache_root = Path(shared_phase1_cache_dir)
        elif shared_analyst_cache_dir:
            phase1_cache_root = Path(shared_analyst_cache_dir) / "phase1_artifacts"

        self.shared_phase1_cache_dir = str(phase1_cache_root) if phase1_cache_root else None
        self.shared_phase1_artifact_cache = (
            SharedPhase1ArtifactCache(self.shared_phase1_cache_dir)
            if self.shared_phase1_cache_dir
            else None
        )
        if shared_analyst_cache_dir:
            self.shared_analyst_cache = SharedAnalystSignalCache(shared_analyst_cache_dir)

        # Setup isolated database
        self.db_path = db_path or self._create_temp_db()
        self._setup_database()

        # Create a unique run_id first (needed by _ensure_config)
        self.run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:8]}"

        # Keep per-adapter config/decision memory isolated, especially in multi-personality runs.
        self.exp_name = f"backtest_{self.personality}_{self.run_id}"

        # Create config
        self.config_id = self._ensure_config()

        # Track current portfolio state
        self.current_portfolio = {
            "id": str(uuid.uuid4()),
            "cashflow": initial_cash,
            "positions": {ticker: {"shares": 0, "value": 0} for ticker in tickers}
        }

        logger.info(
            f"BacktestWorkflowAdapter initialized: {len(tickers)} tickers, "
            f"${initial_cash:,.0f}, analysts={self.analysts}, personality={self.personality}"
        )

    def _adopt_prev_portfolio(self, prev_portfolio: Optional[Dict[str, Any]]) -> None:
        """Merge caller-provided portfolio state while preserving adapter-owned identity fields."""
        if not prev_portfolio:
            return

        merged = dict(self.current_portfolio)
        merged.update(prev_portfolio.copy())
        merged["id"] = prev_portfolio.get("id") or self.current_portfolio["id"]
        merged["positions"] = dict(prev_portfolio.get("positions") or self.current_portfolio.get("positions") or {})
        self.current_portfolio = merged

    def _build_api_source_config(self, base_config: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Build API source config for AgentWorkflow state."""
        from apis.router import build_api_source_config

        return build_api_source_config(self.market, base_config)

    def _create_temp_db(self) -> str:
        """Create a temporary SQLite database for this backtest run (delegates to backtest.workflow.db_store)."""
        return db_store._create_temp_db()

    def _setup_database(self):
        """Initialize SQLite database with required tables (delegates to backtest.workflow.db_store)."""
        db_store._setup_database(self.db_path)

    def _ensure_config(self) -> str:
        """Create or get config entry for this backtest (delegates to backtest.workflow.db_store)."""
        return db_store._ensure_config(
            self.db_path,
            self.exp_name,
            self.tickers,
            self.llm_model,
            self.llm_provider,
        )

    def _get_or_create_portfolio(self, trading_date: str) -> Dict:
        """Get or create portfolio for the trading date (delegates to backtest.workflow.db_store)."""
        return db_store._get_or_create_portfolio(
            self.db_path,
            self.config_id,
            trading_date,
            self.current_portfolio,
        )

    def _update_portfolio(self, trading_date: str):
        """Update portfolio in database after decisions (delegates to backtest.workflow.db_store)."""
        db_store._update_portfolio(self.db_path, self.current_portfolio, trading_date)

    def run_single_day(
        self,
        trading_date: str,
        prices: Dict[str, float],
        prev_portfolio: Optional[Dict] = None
    ) -> Dict[str, BacktestDecision]:
        """
        Run the AgentWorkflow for a single trading day.

        Args:
            trading_date: Trading date in YYYY-MM-DD format
            prices: Dict of {ticker: current_price}
            prev_portfolio: Previous portfolio state (optional, uses internal state)

        Returns:
            Dict of {ticker: BacktestDecision}
        """
        # Use provided portfolio or internal state
        self._adopt_prev_portfolio(prev_portfolio)

        # Ensure portfolio exists for this date
        self._get_or_create_portfolio(trading_date)

        decisions = {}

        try:
            # Import AgentWorkflow components
            from graph.workflow import AgentWorkflow
            from graph.schema import FundState, Portfolio, Position
            from util.db_helper import db_initialize, get_db
            from database.sqlite_helper import SQLiteDB

            db_initialize(use_local_db=True, db_path=self.db_path)
            db = get_db()
            if isinstance(db, SQLiteDB):
                db.set_db_path(self.db_path)

            # Build workflow config
            # Convert trading_date string to datetime for AgentWorkflow compatibility
            trading_date_dt = datetime.strptime(trading_date, "%Y-%m-%d")

            config = {
                "llm": {
                    "provider": self.llm_provider,
                    "model": self.llm_model
                },
                "tickers": self.tickers,
                "exp_name": self.exp_name,  # Fixed exp_name for decision memory
                "trading_date": trading_date_dt,  # datetime object
                "cashflow": self.current_portfolio["cashflow"],
                "workflow_analysts": self.analysts,
                "planner_mode": False,
                "personality": self.personality,
                "api_source": self.api_source,
            }

            # Create Portfolio object from current state
            portfolio = Portfolio(
                id=self.current_portfolio["id"],
                cashflow=self.current_portfolio["cashflow"],
                positions={
                    ticker: Position(
                        shares=pos.get("shares", 0),
                        value=pos.get("value", 0)
                    )
                    for ticker, pos in self.current_portfolio["positions"].items()
                }
            )

            # Run workflow for each ticker
            for ticker in self.tickers:
                if ticker not in prices:
                    logger.warning(f"No price for {ticker} on {trading_date}, skipping")
                    continue

                try:
                    # Build workflow for this ticker
                    workflow = AgentWorkflow(config, self.config_id, self.market)

                    # Override the init_portfolio with our current state
                    workflow.init_portfolio = portfolio

                    # Load analysts
                    workflow.load_analysts(ticker)

                    # Create FundState
                    state = FundState(
                        ticker=ticker,
                        exp_name=config["exp_name"],
                        trading_date=trading_date_dt,  # Use datetime object
                        market=self.market,
                        api_source=self.api_source,
                        llm_config=config["llm"],
                        portfolio=portfolio,
                        num_tickers=len(self.tickers),
                        personality=self.personality,
                        analyst_signals=[],
                        decision=None,
                        current_price=prices[ticker],
                        db_path=self.db_path,
                        is_backtest=True  # Enable backtest mode (skip polymarket, enable timing)
                    )

                    # Build and run workflow
                    graph = workflow.build()
                    final_state = graph.invoke(state)

                    # Extract decision
                    decision = final_state.get("decision")
                    if decision:
                        decisions[ticker] = BacktestDecision(
                            ticker=ticker,
                            action=str(decision.action),
                            shares=decision.shares,
                            price=decision.price,
                            justification=decision.justification,
                            analyst_signals={
                                signal: str(sig.signal)
                                for signal, sig in enumerate(final_state.get("analyst_signals", []))
                            }
                        )

                        # Update portfolio
                        portfolio = workflow.update_portfolio_ticker(
                            portfolio, ticker, decision
                        )

                except Exception as e:
                    logger.error(f"Error processing {ticker} on {trading_date}: {e}")
                    # Fallback to HOLD
                    decisions[ticker] = BacktestDecision(
                        ticker=ticker,
                        action="HOLD",
                        shares=0,
                        price=prices[ticker],
                        justification=f"Error: {str(e)}",
                        analyst_signals={}
                    )

            # Update internal portfolio state
            self.current_portfolio["cashflow"] = portfolio.cashflow
            self.current_portfolio["positions"] = {
                ticker: {"shares": pos.shares, "value": pos.value}
                for ticker, pos in portfolio.positions.items()
            }

            # Update in database
            self._update_portfolio(trading_date)

        except ImportError as e:
            logger.error(f"Failed to import DeepFund modules: {e}")
            # Return HOLD decisions for all tickers
            for ticker in self.tickers:
                if ticker in prices:
                    decisions[ticker] = BacktestDecision(
                        ticker=ticker,
                        action="HOLD",
                        shares=0,
                        price=prices[ticker],
                        justification=f"Import error: {str(e)}",
                        analyst_signals={}
                    )
        finally:
            pass

        return decisions

    def run_single_day_with_precollected_signals(
        self,
        trading_date: str,
        prices: Dict[str, float],
        enhanced_signals: Dict[str, Any],
        priority_order: Optional[List[str]] = None,
        prev_portfolio: Optional[Dict] = None,
    ) -> Dict[str, BacktestDecision]:
        """Run smart-priority phase 2 using caller-provided enhanced analyst signals."""
        self._adopt_prev_portfolio(prev_portfolio)

        self._get_or_create_portfolio(trading_date)

        decisions = {}

        try:
            from graph.schema import FundState, Portfolio, Position  # noqa: F401 — availability probe
            from graph.constants import AgentKey
            from agents.registry import AgentRegistry
            from util.db_helper import db_initialize, get_db
            from database.sqlite_helper import SQLiteDB

            db_initialize(use_local_db=True, db_path=self.db_path)
            db = get_db()
            if isinstance(db, SQLiteDB):
                db.set_db_path(self.db_path)

            trading_date_dt = datetime.strptime(trading_date, "%Y-%m-%d")
            config = {
                "llm": {
                    "provider": self.llm_provider,
                    "model": self.llm_model,
                },
                "tickers": self.tickers,
                "exp_name": self.exp_name,
                "trading_date": trading_date_dt,
                "cashflow": self.current_portfolio["cashflow"],
                "workflow_analysts": self.analysts,
                "planner_mode": False,
                "personality": self.personality,
                "api_source": self.api_source,
            }

            if priority_order:
                seen = set()
                sorted_tickers = []
                for ticker in priority_order:
                    if ticker in enhanced_signals and ticker not in seen:
                        sorted_tickers.append(ticker)
                        seen.add(ticker)
                sorted_tickers.extend(ticker for ticker in enhanced_signals if ticker not in seen)
            else:
                sorted_tickers = self._get_smart_priority_order(enhanced_signals)
            logger.info(f"[Smart Priority] Processing order: {sorted_tickers}")
            logger.info("[Smart Priority] Phase 2: Making decisions in priority order...")

            portfolio_agent = AgentRegistry.get_agent_func_by_key(AgentKey.PORTFOLIO)
            if portfolio_agent is None:
                raise RuntimeError("Portfolio manager agent not registered")

            portfolio = Portfolio(
                id=self.current_portfolio["id"],
                cashflow=self.current_portfolio["cashflow"],
                positions={
                    ticker: Position(
                        shares=pos.get("shares", 0),
                        value=pos.get("value", 0),
                    )
                    for ticker, pos in self.current_portfolio["positions"].items()
                },
            )

            for ticker in sorted_tickers:
                if ticker not in prices:
                    logger.warning(f"No price for {ticker} on {trading_date}, skipping")
                    continue

                try:
                    ticker_signal_data = enhanced_signals.get(ticker, {})
                    pre_collected_signals = ticker_signal_data.get("analyst_signals", [])

                    state = {
                        "ticker": ticker,
                        "exp_name": config["exp_name"],
                        "trading_date": trading_date_dt,
                        "market": self.market,
                        "api_source": self.api_source,
                        "llm_config": config["llm"],
                        "portfolio": portfolio,
                        "num_tickers": len(self.tickers),
                        "personality": self.personality,
                        "analyst_signals": pre_collected_signals,
                        "decision": None,
                        "current_price": prices[ticker],
                        "db_path": self.db_path,
                        "is_backtest": True,
                    }

                    final_state = portfolio_agent(state)
                    decision = final_state.get("decision")
                    if decision:
                        normalized_decision = self._normalize_decision_for_portfolio(portfolio, ticker, decision)
                        decision_signals = final_state.get("analyst_signals") or pre_collected_signals
                        decisions[ticker] = BacktestDecision(
                            ticker=ticker,
                            action=str(normalized_decision.action),
                            shares=normalized_decision.shares,
                            price=normalized_decision.price,
                            justification=normalized_decision.justification,
                            analyst_signals={
                                str(i): str(sig.signal)
                                for i, sig in enumerate(decision_signals)
                            },
                        )

                        portfolio = self._update_portfolio_ticker(portfolio, ticker, normalized_decision)
                        logger.info(
                            f"[Smart Priority] {ticker}: {normalized_decision.action} {normalized_decision.shares} shares "
                            f"(score={ticker_signal_data.get('priority_score', 0.0):.3f})"
                        )
                except Exception as e:
                    logger.error(f"Error processing {ticker} on {trading_date}: {e}")
                    decisions[ticker] = BacktestDecision(
                        ticker=ticker,
                        action="HOLD",
                        shares=0,
                        price=prices.get(ticker, 0.0),
                        justification=f"Error: {str(e)}",
                        analyst_signals={},
                    )

            self.current_portfolio["cashflow"] = portfolio.cashflow
            self.current_portfolio["positions"] = {
                ticker: {"shares": pos.shares, "value": pos.value}
                for ticker, pos in portfolio.positions.items()
            }
            self._update_portfolio(trading_date)
            logger.info(f"[Smart Priority] Completed {len(decisions)} decisions for {trading_date}")

        except ImportError as e:
            logger.error(f"Failed to import DeepFund modules: {e}")
            for ticker in self.tickers:
                if ticker in prices:
                    decisions[ticker] = BacktestDecision(
                        ticker=ticker,
                        action="HOLD",
                        shares=0,
                        price=prices[ticker],
                        justification=f"Import error: {str(e)}",
                        analyst_signals={},
                    )
        finally:
            pass

        return decisions

    def run_single_day_with_smart_priority(
        self,
        trading_date: str,
        prices: Dict[str, float],
        prev_portfolio: Optional[Dict] = None,
        max_workers: int = 5
    ) -> Dict[str, BacktestDecision]:
        """
        Run the AgentWorkflow with smart priority sorting.

        Two-phase approach:
        1. Parallel: Collect all analyst signals for all tickers
        2. Sequential: Make decisions in smart priority order

        This provides:
        - Better performance (parallel signal collection)
        - More rational decision order (prioritize better opportunities)
        - Same correctness (sequential portfolio updates)

        Args:
            trading_date: Trading date in YYYY-MM-DD format
            prices: Dict of {ticker: current_price}
            prev_portfolio: Previous portfolio state (optional)
            max_workers: Max parallel workers for signal collection

        Returns:
            Dict of {ticker: BacktestDecision}
        """
        self._adopt_prev_portfolio(prev_portfolio)

        logger.info("[Smart Priority] Phase 1: Collecting signals in parallel...")
        if self.shared_phase1_artifact_cache is None:
            enhanced_signals = self.collect_signals_only_parallel_v2(
                trading_date,
                prices,
                max_workers,
            )
            return self.run_single_day_with_precollected_signals(
                trading_date=trading_date,
                prices=prices,
                enhanced_signals=enhanced_signals,
                priority_order=self._get_smart_priority_order(enhanced_signals),
                prev_portfolio=self.current_portfolio,
            )

        artifact = self.load_or_compute_shared_phase1(trading_date, prices, max_workers=max_workers)
        return self.run_single_day_with_precollected_signals(
            trading_date=trading_date,
            prices=artifact.prices,
            enhanced_signals=artifact.enhanced_signals,
            priority_order=artifact.priority_order,
            prev_portfolio=self.current_portfolio,
        )

    # Company-news signature / cache-invalidation plumbing (delegates to
    # backtest.workflow.company_news_signature). Same-named delegator
    # methods are kept on this class because
    # tests/test_workflow_adapter_smart_priority.py monkeypatches
    # `_get_company_news_signature_payload` as a class attribute; every
    # module function's internal call goes through the delegator
    # (`adapter.<name>(...)`) rather than a bare module call, so the
    # patch keeps propagating through `_ensure_company_news_prefetched_
    # payload` / `_build_phase1_prefetched_analyst_inputs` /
    # `_resolve_analyst_input_signature` / `_resolve_phase1_input_metadata`.
    _stable_json_signature = staticmethod(company_news_signature._stable_json_signature)

    _normalize_news_item = staticmethod(company_news_signature._normalize_news_item)

    def _get_company_news_signature_payload(self, trading_date: str, ticker: str) -> Dict[str, Any]:
        return company_news_signature._get_company_news_signature_payload(self, trading_date, ticker)

    _get_prefetched_analyst_payload = staticmethod(company_news_signature._get_prefetched_analyst_payload)

    def _ensure_company_news_prefetched_payload(
        self,
        trading_date: str,
        ticker: str,
        prefetched_analyst_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return company_news_signature._ensure_company_news_prefetched_payload(
            self, trading_date, ticker, prefetched_analyst_data
        )

    def _build_phase1_prefetched_analyst_inputs(
        self,
        trading_date: str,
        prices: Dict[str, float],
    ) -> Dict[str, Dict[str, Any]]:
        return company_news_signature._build_phase1_prefetched_analyst_inputs(self, trading_date, prices)

    def _resolve_analyst_input_signature(
        self,
        trading_date: str,
        ticker: str,
        analyst_key: str,
        prefetched_analyst_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        return company_news_signature._resolve_analyst_input_signature(
            self, trading_date, ticker, analyst_key, prefetched_analyst_data
        )

    def _resolve_phase1_input_metadata(
        self,
        trading_date: str,
        prices: Dict[str, float],
        prefetched_analyst_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return company_news_signature._resolve_phase1_input_metadata(
            self, trading_date, prices, prefetched_analyst_inputs
        )

    def _build_shared_phase1_artifact(
        self,
        trading_date: str,
        prices: Dict[str, float],
        enhanced_signals: Dict[str, Any],
        phase1_input_metadata: Optional[Dict[str, Any]] = None,
    ) -> SharedPhase1Artifact:
        return phase1_pipeline._build_shared_phase1_artifact(
            self, trading_date, prices, enhanced_signals, phase1_input_metadata
        )

    def load_or_compute_shared_phase1(
        self,
        trading_date: str,
        prices: Dict[str, float],
        max_workers: int = 5,
    ) -> SharedPhase1Artifact:
        return phase1_pipeline.load_or_compute_shared_phase1(self, trading_date, prices, max_workers)

    # Parallel analyst-signal collection engine (delegates to
    # backtest.workflow.signal_collection). Same-named delegator methods
    # are kept for all six names below because several tests replace
    # `collect_signals_only_parallel_v2` with an instance-level
    # `monkeypatch.setattr(adapter, ...)` or a duck-typed fake adapter
    # entirely (tests/test_multi_personality_day_orchestrator.py,
    # tests/test_fof_engine.py); every internal call between these six
    # (and to the company-news/scoring delegators from earlier Phase 3
    # steps) goes through `self.<name>(...)`, never a direct module call,
    # so any such patch keeps propagating.
    def _process_single_ticker_for_signals_v2(
        self,
        ticker: str,
        trading_date: str,
        trading_date_dt: datetime,
        price: float,
        config: Dict[str, Any],
        portfolio_dict: Dict[str, Any]
    ) -> Dict[str, Any]:
        return signal_collection._process_single_ticker_for_signals_v2(
            self, ticker, trading_date, trading_date_dt, price, config, portfolio_dict
        )

    def _load_shared_analyst_signals(
        self,
        trading_date: str,
        ticker: str,
        analyst_key: str,
        llm_config: Dict[str, Any],
        input_signature: Optional[str] = None,
    ):
        return signal_collection._load_shared_analyst_signals(
            self, trading_date, ticker, analyst_key, llm_config, input_signature
        )

    def _save_shared_analyst_signals(
        self,
        trading_date: str,
        ticker: str,
        analyst_key: str,
        llm_config: Dict[str, Any],
        analyst_signals: List[Any],
        input_signature: Optional[str] = None,
    ) -> None:
        signal_collection._save_shared_analyst_signals(
            self, trading_date, ticker, analyst_key, llm_config, analyst_signals, input_signature
        )

    _signal_has_error = staticmethod(signal_collection._signal_has_error)

    def _calculate_priority_score(self, analyst_signals: List[Any]) -> float:
        """Calculate priority score for smart sorting (delegates to backtest.workflow.scoring)."""
        return scoring._calculate_priority_score(analyst_signals)

    def _calculate_signal_consistency(self, analyst_signals: List[Any]) -> float:
        """Calculate consistency of analyst signals (delegates to backtest.workflow.scoring)."""
        return scoring._calculate_signal_consistency(analyst_signals)

    _signal_label = staticmethod(scoring._signal_label)

    _aggregate_signal_from_summary = staticmethod(scoring._aggregate_signal_from_summary)

    def collect_signals_only(
        self,
        trading_date: str,
        prices: Dict[str, float]
    ) -> Dict[str, Any]:
        """只收集分析师信号，不做最终交易决策（delegates to backtest.workflow.signal_collection）。"""
        return signal_collection.collect_signals_only(self, trading_date, prices)

    def collect_signals_only_parallel_v2(
        self,
        trading_date: str,
        prices: Dict[str, float],
        max_workers: int = 5,
        prefetched_analyst_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Enhanced parallel signal collection (delegates to backtest.workflow.signal_collection)."""
        return signal_collection.collect_signals_only_parallel_v2(
            self, trading_date, prices, max_workers, prefetched_analyst_inputs
        )

    def _get_smart_priority_order(self, signals: Dict[str, Any]) -> List[str]:
        """Determine smart priority order based on collected signals (delegates to backtest.workflow.scoring)."""
        return scoring._get_smart_priority_order(signals, self.tickers)

    def get_current_portfolio(self) -> Dict:
        """Get current portfolio state."""
        return self.current_portfolio.copy()

    _normalize_decision_for_portfolio = staticmethod(decision_apply._normalize_decision_for_portfolio)

    _update_portfolio_ticker = staticmethod(decision_apply._update_portfolio_ticker)

    def close(self):
        """
        Clean up resources and close any open database connections.
        
        This adapter uses short-lived connections that are closed after each
        operation, so this method primarily serves as a cleanup hook and for
        context manager support.
        
        Example:
            # Using context manager (recommended)
            with BacktestWorkflowAdapter(...) as adapter:
                result = adapter.run_single_day(...)
            # Cleanup automatic
            
            # Or explicit close
            adapter = BacktestWorkflowAdapter(...)
            try:
                result = adapter.run_single_day(...)
            finally:
                adapter.close()
        """
        logger.debug(f"BacktestWorkflowAdapter cleanup for {self.exp_name}")
        
        # Note: This adapter uses short-lived connections that are already
        # closed after each operation. Future improvements could include
        # connection pooling or persistent connection management.
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure cleanup."""
        self.close()
        return False  # Don't suppress exceptions
    
    def __del__(self):
        """Destructor - ensure cleanup."""
        try:
            self.close()
        except Exception:
            pass  # Ignore errors during destruction


def create_workflow_adapter(
    tickers: List[str],
    initial_cash: float = 100000.0,
    market: str = "cn",
    use_llm: bool = True,
    analysts: Optional[List[str]] = None,
    personality: str = "balanced",
    db_path: str = "data/signal_flux.db",
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    api_source_config: Optional[Dict[str, str]] = None,
    shared_analyst_cache_dir: Optional[str] = None,
    shared_phase1_cache_dir: Optional[str] = None,
) -> Optional[BacktestWorkflowAdapter]:
    """
    Factory function to create workflow adapter.

    Args:
        tickers: List of ticker symbols
        initial_cash: Starting capital
        market: Market type
        use_llm: Whether to use LLM (returns None if False)
        analysts: List of analysts
        personality: Investment personality
        db_path: SQLite database path

    Returns:
        BacktestWorkflowAdapter or None
    """
    if not use_llm:
        return None

    return BacktestWorkflowAdapter(
        tickers=tickers,
        initial_cash=initial_cash,
        market=market,
        analysts=analysts,
        personality=personality,
        db_path=db_path,
        llm_provider=llm_provider,
        llm_model=llm_model,
        api_source_config=api_source_config,
        shared_analyst_cache_dir=shared_analyst_cache_dir,
        shared_phase1_cache_dir=shared_phase1_cache_dir,
    )
