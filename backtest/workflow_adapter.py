"""
Backtest Workflow Adapter
=========================

Adapter to integrate DeepFund's AgentWorkflow into the backtest framework.
Provides simplified interface for sequential day-by-day trading simulation.
"""

import os
import uuid
import json
import sqlite3
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
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
from backtest.workflow import scoring


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
        """Create a temporary SQLite database for this backtest run."""
        from shared.utils.path_manager import get_project_root
        
        temp_dir = get_project_root() / "data" / "backtest"
        temp_dir.mkdir(parents=True, exist_ok=True)

        db_file = temp_dir / (
            f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:8]}.db"
        )
        return str(db_file)

    def _setup_database(self):
        """Initialize SQLite database with required tables."""
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create config table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS config (
                id VARCHAR(36) PRIMARY KEY,
                exp_name VARCHAR(100) NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tickers JSON NOT NULL,
                has_planner BOOLEAN NOT NULL DEFAULT FALSE,
                llm_model VARCHAR(50) NOT NULL,
                llm_provider VARCHAR(50) NOT NULL
            )
        ''')

        # Create portfolio table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio (
                id VARCHAR(36) PRIMARY KEY,
                config_id VARCHAR(36) NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                trading_date TIMESTAMP NOT NULL,
                cashflow DECIMAL(15,2) NOT NULL,
                total_assets DECIMAL(15,2) NOT NULL,
                positions JSON NOT NULL,
                FOREIGN KEY (config_id) REFERENCES config(id)
            )
        ''')

        # Create decision table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS decision (
                id VARCHAR(36) PRIMARY KEY,
                portfolio_id VARCHAR(36) NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                trading_date TIMESTAMP NOT NULL,
                ticker VARCHAR(10) NOT NULL,
                llm_prompt TEXT NOT NULL,
                action VARCHAR(10) NOT NULL,
                shares INTEGER NOT NULL,
                price DECIMAL(15,2) NOT NULL,
                justification TEXT NOT NULL,
                FOREIGN KEY (portfolio_id) REFERENCES portfolio(id)
            )
        ''')

        # Create signal table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signal (
                id VARCHAR(36) PRIMARY KEY,
                portfolio_id VARCHAR(36) NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ticker VARCHAR(10) NOT NULL,
                llm_prompt TEXT NOT NULL,
                analyst VARCHAR(50) NOT NULL,
                signal VARCHAR(10) NOT NULL,
                justification TEXT NOT NULL,
                FOREIGN KEY (portfolio_id) REFERENCES portfolio(id)
            )
        ''')

        # Create indices
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_config_exp_name ON config(exp_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_portfolio_config ON portfolio(config_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_portfolio_trading_date ON portfolio(trading_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_decision_portfolio ON decision(portfolio_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_portfolio ON signal(portfolio_id)')

        conn.commit()
        conn.close()

        logger.debug(f"Database initialized at {self.db_path}")

    def _ensure_config(self) -> str:
        """Create or get config entry for this backtest."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Use self.exp_name for consistency
        exp_name = self.exp_name

        # Check if config exists
        cursor.execute('SELECT id FROM config WHERE exp_name = ?', (exp_name,))
        row = cursor.fetchone()

        if row:
            conn.close()
            logger.debug(f"Found existing config: {row[0]}")
            return row[0]

        # Create new config
        config_id = str(uuid.uuid4())
        cursor.execute('''
            INSERT INTO config (id, exp_name, updated_at, tickers, has_planner, llm_model, llm_provider)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            config_id,
            exp_name,
            datetime.now().isoformat(),
            json.dumps(self.tickers),
            False,  # no planner for backtest
            self.llm_model,
            self.llm_provider
        ))

        conn.commit()
        conn.close()

        logger.info(f"Created backtest config: {config_id}, exp_name: {exp_name}")
        return config_id

    def _get_or_create_portfolio(self, trading_date: str) -> Dict:
        """Get or create portfolio for the trading date."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create new portfolio entry for this day
        portfolio_id = str(uuid.uuid4())
        total_assets = self.current_portfolio["cashflow"] + sum(
            pos["value"] for pos in self.current_portfolio["positions"].values()
        )

        cursor.execute('''
            INSERT INTO portfolio (id, config_id, updated_at, trading_date, cashflow, total_assets, positions)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            portfolio_id,
            self.config_id,
            datetime.now().isoformat(),
            trading_date,  # Keep as string for our local DB
            self.current_portfolio["cashflow"],
            total_assets,
            json.dumps(self.current_portfolio["positions"])
        ))

        conn.commit()
        conn.close()

        self.current_portfolio["id"] = portfolio_id
        return self.current_portfolio.copy()

    def _update_portfolio(self, trading_date: str):
        """Update portfolio in database after decisions."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        total_assets = self.current_portfolio["cashflow"] + sum(
            pos["value"] for pos in self.current_portfolio["positions"].values()
        )

        cursor.execute('''
            UPDATE portfolio
            SET cashflow = ?, total_assets = ?, positions = ?, updated_at = ?
            WHERE id = ?
        ''', (
            self.current_portfolio["cashflow"],
            total_assets,
            json.dumps(self.current_portfolio["positions"]),
            datetime.now().isoformat(),
            self.current_portfolio["id"]
        ))

        conn.commit()
        conn.close()

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

    @staticmethod
    def _stable_json_signature(payload: Any) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _normalize_news_item(news_item: Any) -> Dict[str, Any]:
        if hasattr(news_item, "model_dump"):
            payload = news_item.model_dump()
        elif isinstance(news_item, dict):
            payload = dict(news_item)
        else:
            payload = {
                "title": getattr(news_item, "title", None),
                "publish_time": getattr(news_item, "publish_time", None),
                "publisher": getattr(news_item, "publisher", None),
                "link": getattr(news_item, "link", None),
                "summary": getattr(news_item, "summary", None),
            }
        return {
            "title": payload.get("title"),
            "publish_time": payload.get("publish_time"),
            "publisher": payload.get("publisher"),
            "link": payload.get("link"),
            "summary": payload.get("summary"),
        }

    def _get_company_news_signature_payload(self, trading_date: str, ticker: str) -> Dict[str, Any]:
        from apis.router import Router, resolve_api_source
        from util.threshold_config import get_threshold_config

        trading_date_dt = datetime.strptime(trading_date, "%Y-%m-%d")
        news_count = int(get_threshold_config().get_thresholds("company_news").get("news_count", 10))
        api_source = resolve_api_source(self.market, self.api_source)
        router = Router(api_source)
        if self.market == "cn":
            news_items = router.get_cn_stock_news(ticker, trading_date_dt, news_count)
        else:
            news_items = router.get_us_stock_news(ticker, trading_date_dt, news_count)

        prompt_data = [
            item.model_dump_json() if hasattr(item, "model_dump_json") else json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in (news_items or [])
        ]
        normalized_items = [
            self._normalize_news_item(item)
            for item in (news_items or [])
        ]
        payload = {
            "ticker": ticker,
            "trading_date": trading_date,
            "count": len(normalized_items),
            "items": normalized_items,
            "prompt_data": prompt_data,
            "signature": self._stable_json_signature(prompt_data),
        }
        return payload

    @staticmethod
    def _get_prefetched_analyst_payload(
        prefetched_analyst_data: Optional[Dict[str, Any]],
        analyst_key: str,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(prefetched_analyst_data, dict):
            return None
        payload = prefetched_analyst_data.get(analyst_key)
        return payload if isinstance(payload, dict) else None

    def _ensure_company_news_prefetched_payload(
        self,
        trading_date: str,
        ticker: str,
        prefetched_analyst_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = self._get_prefetched_analyst_payload(prefetched_analyst_data, "company_news")
        if payload is None:
            payload = self._get_company_news_signature_payload(trading_date, ticker)
            if isinstance(prefetched_analyst_data, dict):
                prefetched_analyst_data["company_news"] = payload
        return payload

    def _build_phase1_prefetched_analyst_inputs(
        self,
        trading_date: str,
        prices: Dict[str, float],
    ) -> Dict[str, Dict[str, Any]]:
        prefetched_inputs: Dict[str, Dict[str, Any]] = {}
        if "company_news" not in self.analysts:
            return prefetched_inputs
        for ticker in sorted(prices):
            prefetched_inputs.setdefault(ticker, {})["company_news"] = self._get_company_news_signature_payload(
                trading_date,
                ticker,
            )
        return prefetched_inputs

    def _resolve_analyst_input_signature(
        self,
        trading_date: str,
        ticker: str,
        analyst_key: str,
        prefetched_analyst_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if analyst_key == "company_news":
            payload = self._ensure_company_news_prefetched_payload(
                trading_date,
                ticker,
                prefetched_analyst_data,
            )
            return str(payload["signature"])
        return None

    def _resolve_phase1_input_metadata(
        self,
        trading_date: str,
        prices: Dict[str, float],
        prefetched_analyst_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        prices_signature = SharedPhase1ArtifactCache._prices_signature(prices)
        tickers_signature = SharedPhase1ArtifactCache._signature(sorted(prices.keys()))
        metadata: Dict[str, Any] = {
            "price_input_signature": prices_signature,
            "tickers_input_signature": tickers_signature,
        }
        component_signatures: Dict[str, Any] = {
            "prices": prices_signature,
            "tickers": tickers_signature,
        }

        if "company_news" in self.analysts:
            news_by_ticker: Dict[str, str] = {}
            prefetched_analyst_inputs = prefetched_analyst_inputs or {}
            for ticker in sorted(prices):
                payload = self._ensure_company_news_prefetched_payload(
                    trading_date,
                    ticker,
                    prefetched_analyst_inputs.setdefault(ticker, {}),
                )
                news_by_ticker[ticker] = str(payload["signature"])
            news_signature = self._stable_json_signature(news_by_ticker)
            metadata["news_input_signature"] = news_signature
            metadata["news_input_signatures_by_ticker"] = news_by_ticker
            component_signatures["company_news"] = news_signature

        phase1_input_signature = self._stable_json_signature(component_signatures)
        metadata["phase1_input_signature"] = phase1_input_signature
        return metadata

    def _build_shared_phase1_artifact(
        self,
        trading_date: str,
        prices: Dict[str, float],
        enhanced_signals: Dict[str, Any],
        phase1_input_metadata: Optional[Dict[str, Any]] = None,
    ) -> SharedPhase1Artifact:
        phase1_input_metadata = dict(phase1_input_metadata or {})
        return SharedPhase1Artifact(
            trading_date=trading_date,
            prices=dict(prices),
            enhanced_signals=enhanced_signals,
            priority_order=self._get_smart_priority_order(enhanced_signals),
            metadata={
                "market": self.market,
                "tickers": list(self.tickers),
                "analysts": list(self.analysts),
                "llm_provider": self.llm_provider,
                "llm_model": self.llm_model,
                "generated_at": datetime.now(UTC).isoformat(),
                "artifact_version": self.SHARED_PHASE1_ARTIFACT_VERSION,
                "priority_score_version": SharedPhase1ArtifactCache.PRIORITY_SCORE_VERSION,
                "cache_hit": False,
                "price_input_signature": SharedPhase1ArtifactCache._prices_signature(prices),
                **phase1_input_metadata,
            },
        )

    def load_or_compute_shared_phase1(
        self,
        trading_date: str,
        prices: Dict[str, float],
        max_workers: int = 5,
    ) -> SharedPhase1Artifact:
        artifact: Optional[SharedPhase1Artifact] = None
        phase1_input_metadata: Dict[str, Any] = {}
        prefetched_analyst_inputs: Dict[str, Dict[str, Any]] = {}
        shared_phase1_cache_enabled = self.shared_phase1_artifact_cache is not None

        if shared_phase1_cache_enabled:
            try:
                prefetched_analyst_inputs = self._build_phase1_prefetched_analyst_inputs(trading_date, prices)
                phase1_input_metadata = self._resolve_phase1_input_metadata(
                    trading_date,
                    prices,
                    prefetched_analyst_inputs=prefetched_analyst_inputs,
                )
            except Exception as signature_error:
                shared_phase1_cache_enabled = False
                prefetched_analyst_inputs = {}
                logger.warning(
                    f"Shared phase1 input signature resolution failed for {trading_date}; bypassing cache: {signature_error}"
                )

        if shared_phase1_cache_enabled:
            try:
                artifact = self.shared_phase1_artifact_cache.load(
                    trading_date=trading_date,
                    market=self.market,
                    tickers=self.tickers,
                    analysts=self.analysts,
                    llm_provider=self.llm_provider,
                    llm_model=self.llm_model,
                    prices=prices,
                    phase1_input_signature=str(phase1_input_metadata["phase1_input_signature"]),
                )
            except Exception as cache_error:
                logger.warning(f"Shared phase1 artifact cache load failed for {trading_date}: {cache_error}")
                artifact = None

        if artifact is not None:
            artifact.prices = dict(prices)
            artifact.metadata = {
                **artifact.metadata,
                **phase1_input_metadata,
                "resolved_at": datetime.now(UTC).isoformat(),
                "cache_hit": True,
            }
            return artifact

        if prefetched_analyst_inputs:
            enhanced_signals = self.collect_signals_only_parallel_v2(
                trading_date,
                prices,
                max_workers,
                prefetched_analyst_inputs=prefetched_analyst_inputs,
            )
        else:
            enhanced_signals = self.collect_signals_only_parallel_v2(
                trading_date,
                prices,
                max_workers,
            )
        artifact = self._build_shared_phase1_artifact(
            trading_date,
            prices,
            enhanced_signals,
            phase1_input_metadata=phase1_input_metadata,
        )

        if shared_phase1_cache_enabled:
            try:
                self.shared_phase1_artifact_cache.save(
                    trading_date=trading_date,
                    market=self.market,
                    tickers=self.tickers,
                    analysts=self.analysts,
                    llm_provider=self.llm_provider,
                    llm_model=self.llm_model,
                    prices=prices,
                    phase1_input_signature=str(phase1_input_metadata["phase1_input_signature"]),
                    artifact=artifact,
                )
            except Exception as cache_error:
                logger.warning(f"Shared phase1 artifact cache save failed for {trading_date}: {cache_error}")

        return artifact

    def _process_single_ticker_for_signals_v2(
        self,
        ticker: str,
        trading_date: str,
        trading_date_dt: datetime,
        price: float,
        config: Dict[str, Any],
        portfolio_dict: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single ticker to collect ALL analyst signals.
        Enhanced version for smart priority sorting.

        Returns:
            Enhanced signal dict with all analyst signals and metadata.
        """
        from agents.registry import AgentRegistry
        from graph.schema import FundState, Portfolio, Position, AnalystSignal
        from graph.constants import Signal

        # Create a copy of portfolio for this thread
        portfolio = Portfolio(
            id=portfolio_dict["id"],
            cashflow=portfolio_dict["cashflow"],
            positions={
                t: Position(
                    shares=pos.get("shares", 0),
                    value=pos.get("value", 0)
                )
                for t, pos in portfolio_dict["positions"].items()
            }
        )

        try:
            prefetched_analyst_data = dict(config.get("prefetched_analyst_inputs", {}).get(ticker, {}))
            state = FundState(
                ticker=ticker,
                exp_name=config["exp_name"],
                trading_date=trading_date_dt,
                market=self.market,
                api_source=self.api_source,
                llm_config=config["llm"],
                portfolio=portfolio,
                num_tickers=len(config["tickers"]),
                personality=self.personality,
                analyst_signals=[],
                decision=None,
                current_price=price,
                db_path=self.db_path,
                is_backtest=True,
                skip_db_writes=True,
                prefetched_analyst_data=prefetched_analyst_data,
            )

            workflow_analysts = config.get("workflow_analysts", [])
            valid_analysts = [a for a in workflow_analysts if AgentRegistry.check_agent_key(a)]
            invalid_analysts = [a for a in workflow_analysts if a not in valid_analysts]
            if invalid_analysts:
                logger.warning(f"Skipping invalid analysts for {ticker}: {invalid_analysts}")

            # Run analysts only and collect all emitted signals.
            analyst_signals: List[AnalystSignal] = []
            for analyst_key in valid_analysts:
                analyst_input_signature: Optional[str] = None
                try:
                    analyst_input_signature = self._resolve_analyst_input_signature(
                        trading_date,
                        ticker,
                        analyst_key,
                        prefetched_analyst_data,
                    )
                except Exception as signature_error:
                    logger.warning(
                        f"Shared analyst input signature resolution failed for {analyst_key} {ticker} {trading_date}: {signature_error}"
                    )

                cached_signals = self._load_shared_analyst_signals(
                    trading_date=trading_date,
                    ticker=ticker,
                    analyst_key=analyst_key,
                    llm_config=config["llm"],
                    input_signature=analyst_input_signature,
                )
                if cached_signals is not None:
                    analyst_signals.extend(cached_signals)
                    continue

                analyst_func = AgentRegistry.get_agent_func_by_key(analyst_key)
                if analyst_func is None:
                    logger.warning(f"Analyst function not found: {analyst_key}")
                    continue

                try:
                    result = analyst_func(state)
                    new_signals = result.get("analyst_signals", [])
                    analyst_signals.extend(new_signals)
                    self._save_shared_analyst_signals(
                        trading_date=trading_date,
                        ticker=ticker,
                        analyst_key=analyst_key,
                        llm_config=config["llm"],
                        analyst_signals=new_signals,
                        input_signature=analyst_input_signature,
                    )
                except Exception as analyst_error:
                    logger.error(f"Analyst {analyst_key} failed for {ticker}: {analyst_error}")
                    analyst_signals.append(
                        AnalystSignal(
                            signal=Signal.NEUTRAL,
                            justification=f"[Error] {analyst_key} failed: {analyst_error}",
                        )
                    )

            # Calculate priority score
            priority_score = self._calculate_priority_score(analyst_signals)

            return {
                "ticker": ticker,
                "price": price,
                "analyst_signals": analyst_signals,
                "priority_score": priority_score,
                "summary": {
                    "bullish_count": sum(1 for s in analyst_signals if self._signal_label(s) == "BULLISH"),
                    "bearish_count": sum(1 for s in analyst_signals if self._signal_label(s) == "BEARISH"),
                    "neutral_count": sum(1 for s in analyst_signals if self._signal_label(s) == "NEUTRAL"),
                    "avg_confidence": sum(getattr(s, 'confidence', 0.5) for s in analyst_signals) / len(analyst_signals) if analyst_signals else 0.0,
                    "signal_consistency": self._calculate_signal_consistency(analyst_signals)
                }
            }
        except Exception as e:
            import traceback
            logger.error(f"Error collecting signals for {ticker} on {trading_date}: {e}")
            logger.error(traceback.format_exc())
            return {
                "ticker": ticker,
                "price": price,
                "analyst_signals": [],
                "priority_score": 0.0,
                "summary": {
                    "bullish_count": 0,
                    "bearish_count": 0,
                    "neutral_count": 0,
                    "avg_confidence": 0.0,
                    "signal_consistency": 0.0
                }
            }

    def _load_shared_analyst_signals(
        self,
        trading_date: str,
        ticker: str,
        analyst_key: str,
        llm_config: Dict[str, Any],
        input_signature: Optional[str] = None,
    ):
        if self.shared_analyst_cache is None:
            return None
        try:
            signals = self.shared_analyst_cache.load(
                trading_date=trading_date,
                market=self.market,
                ticker=ticker,
                analyst_key=analyst_key,
                llm_provider=str(llm_config.get("provider", "")),
                llm_model=str(llm_config.get("model", "")),
                input_signature=input_signature,
            )
        except Exception as cache_error:
            logger.warning(
                f"Shared analyst cache load failed for {analyst_key} {ticker} {trading_date}: {cache_error}"
            )
            return None
        if signals is not None:
            logger.debug(f"Shared analyst cache hit: {analyst_key} {ticker} {trading_date}")
        return signals

    def _save_shared_analyst_signals(
        self,
        trading_date: str,
        ticker: str,
        analyst_key: str,
        llm_config: Dict[str, Any],
        analyst_signals: List[Any],
        input_signature: Optional[str] = None,
    ) -> None:
        if self.shared_analyst_cache is None or not analyst_signals:
            return
        if any(self._signal_has_error(signal) for signal in analyst_signals):
            return
        try:
            self.shared_analyst_cache.save(
                trading_date=trading_date,
                market=self.market,
                ticker=ticker,
                analyst_key=analyst_key,
                llm_provider=str(llm_config.get("provider", "")),
                llm_model=str(llm_config.get("model", "")),
                analyst_signals=analyst_signals,
                input_signature=input_signature,
            )
        except Exception as cache_error:
            logger.warning(
                f"Shared analyst cache save failed for {analyst_key} {ticker} {trading_date}: {cache_error}"
            )

    @staticmethod
    def _signal_has_error(signal: Any) -> bool:
        justification = getattr(signal, "justification", "")
        if not isinstance(justification, str):
            return False
        return justification.startswith("[Error]")

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
        """
        只收集分析师信号，不做最终交易决策。
        用于 B1 方案：先收集所有股票信号，再统一做组合分配。

        Args:
            trading_date: 交易日期 (YYYY-MM-DD)
            prices: {ticker: price} 当前价格

        Returns:
            {ticker: dict} 每只股票的聚合信号，保留 summary 以兼容 profile-specific logic
        """
        # Use enhanced version with smart priority
        enhanced_signals = self.collect_signals_only_parallel_v2(trading_date, prices)

        # Convert to old format for backward compatibility
        signals = {}
        for ticker, data in enhanced_signals.items():
            summary = dict(data.get("summary", {}) or {})
            bullish = int(summary.get("bullish_count", 0) or 0)
            bearish = int(summary.get("bearish_count", 0) or 0)
            neutral = int(summary.get("neutral_count", 0) or 0)
            signals[ticker] = {
                "ticker": ticker,
                "signal": self._aggregate_signal_from_summary(summary),
                "justification": (
                    "Enhanced signals with priority score "
                    f"{data.get('priority_score', 0.0)}; counts "
                    f"B={bullish}, N={neutral}, BR={bearish}"
                ),
                "confidence": summary.get("avg_confidence", 0.5),
                "summary": summary,
                "priority_score": data.get("priority_score", 0.0),
                "analyst_signals": list(data.get("analyst_signals", []) or []),
            }

        return signals

    def collect_signals_only_parallel_v2(
        self,
        trading_date: str,
        prices: Dict[str, float],
        max_workers: int = 5,
        prefetched_analyst_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Enhanced parallel version for smart priority sorting.
        Collects ALL analyst signals with priority scores.

        Args:
            trading_date: 交易日期 (YYYY-MM-DD)
            prices: {ticker: price} 当前价格
            max_workers: 最大并行线程数 (默认 5)

        Returns:
            {ticker: EnhancedSignal} 包含所有分析师信号和优先级评分
        """
        signals = {}
        signals_lock = Lock()

        try:
            from util.db_helper import db_initialize, get_db
            from database.sqlite_helper import SQLiteDB

            db_initialize(use_local_db=True, db_path=self.db_path)
            db = get_db()
            if isinstance(db, SQLiteDB):
                db.set_db_path(self.db_path)

            trading_date_dt = datetime.strptime(trading_date, "%Y-%m-%d")

            # Build workflow config (shared across all threads)
            config = {
                "llm": {
                    "provider": self.llm_provider,
                    "model": self.llm_model
                },
                "tickers": self.tickers,
                "exp_name": self.exp_name,
                "trading_date": trading_date_dt,
                "cashflow": self.current_portfolio["cashflow"],
                "workflow_analysts": self.analysts,
                "planner_mode": False,
                "personality": self.personality,
                "api_source": self.api_source,
                "prefetched_analyst_inputs": prefetched_analyst_inputs or {},
            }

            # Create Portfolio dict for serialization across threads
            portfolio_dict = {
                "id": self.current_portfolio["id"],
                "cashflow": self.current_portfolio["cashflow"],
                "positions": self.current_portfolio["positions"]
            }

            # Filter tickers that have prices
            tickers_to_process = [t for t in self.tickers if t in prices]
            if len(tickers_to_process) < len(self.tickers):
                missing = set(self.tickers) - set(tickers_to_process)
                logger.warning(f"No price for {missing} on {trading_date}, skipping")

            # Process tickers in parallel using ThreadPoolExecutor
            logger.info(f"Processing {len(tickers_to_process)} tickers with {max_workers} workers for smart priority")

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                future_to_ticker = {
                    executor.submit(
                        self._process_single_ticker_for_signals_v2,
                        ticker,
                        trading_date,
                        trading_date_dt,
                        prices[ticker],
                        config,
                        portfolio_dict
                    ): ticker
                    for ticker in tickers_to_process
                }

                # Collect results as they complete
                for future in as_completed(future_to_ticker):
                    ticker = future_to_ticker[future]
                    try:
                        result = future.result()
                        if result:
                            with signals_lock:
                                signals[result["ticker"]] = result
                    except Exception as e:
                        logger.error(f"Thread error for {ticker}: {e}")
                        with signals_lock:
                            signals[ticker] = {
                                "ticker": ticker,
                                "price": prices.get(ticker, 0.0),
                                "analyst_signals": [],
                                "priority_score": 0.0,
                                "summary": {
                                    "bullish_count": 0,
                                    "bearish_count": 0,
                                    "neutral_count": 0,
                                    "avg_confidence": 0.0,
                                    "signal_consistency": 0.0
                                }
                            }

        except ImportError as e:
            logger.error(f"Failed to import DeepFund modules: {e}")
            # Return empty signals for all
            for ticker in self.tickers:
                if ticker in prices:
                    signals[ticker] = {
                        "ticker": ticker,
                        "price": prices[ticker],
                        "analyst_signals": [],
                        "priority_score": 0.0,
                        "summary": {
                            "bullish_count": 0,
                            "bearish_count": 0,
                            "neutral_count": 0,
                            "avg_confidence": 0.0,
                            "signal_consistency": 0.0
                        }
                    }

        finally:
            pass

        logger.info(f"Collected enhanced signals for {len(signals)} tickers on {trading_date}")
        return signals

    def _get_smart_priority_order(self, signals: Dict[str, Any]) -> List[str]:
        """Determine smart priority order based on collected signals (delegates to backtest.workflow.scoring)."""
        return scoring._get_smart_priority_order(signals, self.tickers)

    def get_current_portfolio(self) -> Dict:
        """Get current portfolio state."""
        return self.current_portfolio.copy()

    @staticmethod
    def _normalize_decision_for_portfolio(portfolio: Any, ticker: str, decision: Any) -> Any:
        """Clamp a decision to the shares currently executable for the working portfolio."""
        from graph.constants import Action
        from graph.schema import Decision, Position

        action = str(getattr(decision, "action", "HOLD")).strip().upper()
        requested_shares = max(int(getattr(decision, "shares", 0) or 0), 0)
        price = float(getattr(decision, "price", 0.0) or 0.0)
        justification = str(getattr(decision, "justification", "") or "")

        if ticker not in portfolio.positions:
            portfolio.positions[ticker] = Position(shares=0, value=0)

        current_shares = int(getattr(portfolio.positions[ticker], "shares", 0) or 0)
        affordable_shares = int(portfolio.cashflow // price) if price > 0 else 0

        executable_shares = 0
        normalized_action = action
        if action == "BUY":
            executable_shares = min(requested_shares, affordable_shares)
            if executable_shares <= 0:
                normalized_action = "HOLD"
        elif action == "SELL":
            executable_shares = min(requested_shares, current_shares)
            if executable_shares <= 0:
                normalized_action = "HOLD"
        else:
            normalized_action = "HOLD"

        action_enum = Action.HOLD
        if normalized_action == "BUY":
            action_enum = Action.BUY
        elif normalized_action == "SELL":
            action_enum = Action.SELL

        return Decision(
            action=action_enum,
            shares=executable_shares,
            price=price,
            justification=justification,
        )

    @staticmethod
    def _update_portfolio_ticker(portfolio: Any, ticker: str, decision: Any) -> Any:
        """Update one ticker in portfolio based on a portfolio manager decision."""
        from graph.schema import Position

        action = str(getattr(decision, "action", "HOLD")).strip().upper()
        shares = int(getattr(decision, "shares", 0) or 0)
        price = float(getattr(decision, "price", 0.0) or 0.0)

        if ticker not in portfolio.positions:
            portfolio.positions[ticker] = Position(shares=0, value=0)

        if action == "BUY":
            portfolio.positions[ticker].shares += shares
            portfolio.cashflow -= price * shares
        elif action == "SELL":
            portfolio.positions[ticker].shares -= shares
            portfolio.cashflow += price * shares

        portfolio.positions[ticker].value = round(price * portfolio.positions[ticker].shares, 2)
        portfolio.cashflow = round(portfolio.cashflow, 2)
        return portfolio

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
