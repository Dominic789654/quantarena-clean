"""
DeepEar Client - Integration layer for DeepEar's intelligence analysis capabilities.

This module provides a simplified interface to DeepEar's multi-agent financial
intelligence system, specifically focusing on the ISQ (Investment Signal Quality)
framework for analyzing A-share market opportunities.
"""

import os
import sys
import asyncio
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from loguru import logger
from dataclasses import dataclass, field

# Add DeepEar to path
DEEPEAR_PATH = Path(os.environ.get("DEEPEAR_PATH", "deepear"))
DEEPEAR_SRC_PATH = DEEPEAR_PATH / "src"
if str(DEEPEAR_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(DEEPEAR_SRC_PATH))

# Try to import DeepEar components
try:
    from schema.models import InvestmentSignal
    DEEPEAR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"DeepEar not available: {e}")
    DEEPEAR_AVAILABLE = False
    InvestmentSignal = None


class ISQScore:
    """
    ISQ (Investment Signal Quality) score representation.

    This maps DeepEar's ISQ framework to a simplified format for DeepFund.
    """
    def __init__(
        self,
        sentiment: float,        # -1.0 to 1.0 (bearish to bullish)
        confidence: float,       # 0.0 to 1.0 (certainty)
        intensity: int,          # 1 to 5 (impact magnitude)
        expectation_gap: float,  # 0.0 to 1.0 (market vs reality gap)
        timeliness: float,       # 0.0 to 1.0 (time urgency)
    ):
        self.sentiment = sentiment
        self.confidence = confidence
        self.intensity = intensity
        self.expectation_gap = expectation_gap
        self.timeliness = timeliness

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sentiment": self.sentiment,
            "confidence": self.confidence,
            "intensity": self.intensity,
            "expectation_gap": self.expectation_gap,
            "timeliness": self.timeliness,
        }

    @classmethod
    def from_investment_signal(cls, signal: Any) -> "ISQScore":
        """Create ISQScore from DeepEar's InvestmentSignal."""
        if signal is None:
            return cls(0.0, 0.5, 3, 0.5, 0.5)

        return cls(
            sentiment=getattr(signal, 'sentiment_score', 0.0),
            confidence=getattr(signal, 'confidence', 0.5),
            intensity=getattr(signal, 'intensity', 3),
            expectation_gap=getattr(signal, 'expectation_gap', 0.5),
            timeliness=getattr(signal, 'timeliness', 0.5),
        )

    def calculate_overall_score(self) -> float:
        """
        Calculate overall ISQ score using DeepEar's formula:
        Overall = Confidence * 0.35 + (Intensity/5) * 0.30 + Expectation Gap * 0.20 + Timeliness * 0.15
        """
        return (
            self.confidence * 0.35 +
            (self.intensity / 5) * 0.30 +
            self.expectation_gap * 0.20 +
            self.timeliness * 0.15
        )


def isq_to_signal(isq_score: ISQScore) -> str:
    """
    Convert ISQ score to DeepFund signal type.

    Mapping Logic:
    - sentiment > 0.3 AND confidence > 0.6 → BULLISH
    - sentiment < -0.3 AND confidence > 0.6 → BEARISH
    - else → NEUTRAL
    """
    if isq_score.sentiment > 0.3 and isq_score.confidence > 0.6:
        return "Bullish"
    elif isq_score.sentiment < -0.3 and isq_score.confidence > 0.6:
        return "Bearish"
    else:
        return "Neutral"


@dataclass
class DeepEarTimingStats:
    """Timing statistics for DeepEar analysis steps."""
    total_time: float = 0.0
    step_times: Dict[str, float] = field(default_factory=dict)
    step_timeouts: List[str] = field(default_factory=list)

    def record_step(self, step_name: str, duration: float):
        """Record a step's duration."""
        self.step_times[step_name] = duration
        self.total_time += duration

    def record_timeout(self, step_name: str):
        """Record a step that timed out."""
        self.step_timeouts.append(step_name)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/reporting."""
        return {
            "total_time_sec": round(self.total_time, 2),
            "step_times_sec": {k: round(v, 2) for k, v in self.step_times.items()},
            "step_timeouts": self.step_timeouts,
        }

    def summary(self) -> str:
        """Generate a human-readable summary."""
        lines = [f"DeepEar Timing Summary (total: {self.total_time:.1f}s):"]
        for step, duration in sorted(self.step_times.items(), key=lambda x: -x[1]):
            timeout_mark = " ⏱️ TIMEOUT" if step in self.step_timeouts else ""
            lines.append(f"  - {step}: {duration:.1f}s{timeout_mark}")
        return "\n".join(lines)


class DeepEarClient:
    """
    Client for integrating DeepEar's intelligence analysis into DeepFund.

    This client provides a simplified interface to DeepEar's capabilities,
    focusing on the ISQ scoring framework for investment signal quality assessment.
    """

    # Per-step timeout limits (in seconds)
    STEP_TIMEOUTS = {
        "trend_agent": 150,      # TrendAgent: news fetch + evaluation (increased from 120s)
        "fin_agent_research": 60, # FinAgent research phase
        "fin_agent_analysis": 90, # FinAgent analysis phase
    }
    DEFAULT_STEP_TIMEOUT = 60

    def __init__(self, db_path: Optional[str] = None, skip_polymarket: bool = False, enable_timing: bool = True):
        """
        Initialize the DeepEar client.

        Args:
            db_path: Optional path to DeepEar's database. If not provided,
                     uses the default from DeepEar's config.
            skip_polymarket: Skip Polymarket toolkit (recommended for backtest, network unreachable)
            enable_timing: Enable timing statistics collection
        """
        self.available = DEEPEAR_AVAILABLE
        self.skip_polymarket = skip_polymarket
        self.enable_timing = enable_timing
        self._last_timing_stats: Optional[DeepEarTimingStats] = None

        # Use default db path if not provided
        if db_path is None:
            self.db_path = str(DEEPEAR_PATH / "data" / "signal_flux.db")
        else:
            self.db_path = db_path

        if not self.available:
            logger.warning("DeepEar integration not available. Using mock analysis.")
        if skip_polymarket:
            logger.info("DeepEar: Polymarket toolkit disabled (backtest mode)")

    def get_last_timing_stats(self) -> Optional[Dict[str, Any]]:
        """Get timing statistics from the last analysis."""
        if self._last_timing_stats:
            return self._last_timing_stats.to_dict()
        return None

    def analyze_ticker(
        self,
        ticker: str,
        trading_date: Optional[datetime] = None,
        sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a single ticker using DeepEar's intelligence.

        Args:
            ticker: Stock code to analyze (e.g., '600519' for Kweichow Moutai)
            trading_date: Trading date for analysis
            sources: News sources to analyze (default: ['cls', 'wallstreetcn'])

        Returns:
            Dictionary containing:
            - signal: "Bullish", "Bearish", or "Neutral"
            - isq_score: ISQ score components
            - overall_score: Overall ISQ score (0-1)
            - justification: Explanation for the signal
            - summary: Brief summary of the analysis
            - timing: Timing statistics (if enabled)
        """
        if not self.available:
            return self._mock_analyze_ticker(ticker, trading_date)

        sources = sources or ["cls", "wallstreetcn"]

        try:
            # Run DeepEar analysis in a separate thread with its own event loop
            # This is necessary because agno uses asyncio internally
            result = self._run_in_thread_with_loop(
                self._analyze_ticker_impl,
                ticker,
                trading_date,
                sources
            )
            # Add timing stats to result
            if self.enable_timing and self._last_timing_stats:
                result["timing"] = self._last_timing_stats.to_dict()
            return result
        except Exception as e:
            logger.error(f"DeepEar analysis failed for {ticker}: {e}")
            return self._mock_analyze_ticker(ticker, trading_date, error=str(e))

    def _run_in_thread_with_loop(self, func, *args, **kwargs):
        """
        Run a function in a new thread with its own event loop.
        This is needed because agno uses asyncio and LangGraph runs in a thread pool.
        """
        import threading
        import importlib

        result = {}
        exception = [None]

        def run_in_thread():
            try:
                # Set up a completely fresh import environment
                deepear_src = str(DEEPEAR_SRC_PATH)

                # Remove any existing references and re-add at position 0
                while deepear_src in sys.path:
                    sys.path.remove(deepear_src)
                sys.path.insert(0, deepear_src)

                # Clear any cached imports from these modules
                modules_to_clear = [
                    k for k in sys.modules.keys()
                    if k.startswith('agents.') or k.startswith('utils.') or k.startswith('schema.')
                ]
                for mod in modules_to_clear:
                    del sys.modules[mod]

                importlib.invalidate_caches()

                # Create a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result['value'] = func(*args, **kwargs)
                finally:
                    loop.close()
            except Exception as e:
                import traceback
                exception[0] = e
                logger.error(f"DeepEar thread error: {e}\n{traceback.format_exc()}")

        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join(timeout=300)  # 5 minute timeout for DeepEar analysis

        if exception[0]:
            raise exception[0]
        if thread.is_alive():
            raise TimeoutError("DeepEar analysis timed out")

        return result.get('value')

    def _analyze_ticker_impl(
        self,
        ticker: str,
        trading_date: Optional[datetime],
        sources: List[str],
    ) -> Dict[str, Any]:
        """Internal implementation of ticker analysis with per-step timing."""
        import importlib.util
        import signal as sig

        deepear_src = str(DEEPEAR_SRC_PATH)

        # Initialize timing stats
        timing = DeepEarTimingStats() if self.enable_timing else None

        # Helper function to load module from file path
        def load_module_from_path(module_name: str, file_path: str):
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module

        # Load schema models first (dependency)
        schema_path = f"{deepear_src}/schema/models.py"
        load_module_from_path("schema.models", schema_path)

        # Load utils modules
        db_manager_path = f"{deepear_src}/utils/database_manager.py"
        router_path = f"{deepear_src}/utils/llm/router.py"

        # Create utils package if needed
        if "utils" not in sys.modules:
            utils_init = importlib.util.module_from_spec(
                importlib.util.spec_from_file_location("utils", f"{deepear_src}/utils/__init__.py")
            )
            sys.modules["utils"] = utils_init

        db_module = load_module_from_path("utils.database_manager", db_manager_path)
        router_module = load_module_from_path("utils.llm.router", router_path)

        # Load agents modules
        trend_agent_path = f"{deepear_src}/agents/trend_agent.py"
        fin_agent_path = f"{deepear_src}/agents/fin_agent.py"

        # Create agents package if needed
        if "agents" not in sys.modules:
            agents_init = importlib.util.module_from_spec(
                importlib.util.spec_from_file_location("agents", f"{deepear_src}/agents/__init__.py")
            )
            sys.modules["agents"] = agents_init

        trend_module = load_module_from_path("agents.trend_agent", trend_agent_path)
        fin_module = load_module_from_path("agents.fin_agent", fin_agent_path)

        # Get classes
        DatabaseManager = db_module.DatabaseManager
        ModelRouter = router_module.ModelRouter
        TrendAgent = trend_module.TrendAgent
        FinAgent = fin_module.FinAgent

        # Initialize database
        db = DatabaseManager(db_path=self.db_path)

        # Get models using ModelRouter
        router = ModelRouter()
        reasoning_model = router.get_reasoning_model()
        tool_model = router.get_tool_model()

        # Run TrendAgent to discover signals (with timing)
        trend_agent = TrendAgent(
            db=db, model=reasoning_model, tool_model=tool_model,
            skip_polymarket=self.skip_polymarket
        )

        trend_result = None
        step_start = time.time()
        try:
            trend_result = trend_agent.discover_daily_signals(focus_sources=sources)
            if timing:
                timing.record_step("trend_agent", time.time() - step_start)
                logger.info(f"⏱️ TrendAgent completed in {timing.step_times['trend_agent']:.1f}s")
        except Exception as e:
            if timing:
                timing.record_step("trend_agent", time.time() - step_start)
                timing.record_timeout("trend_agent")
            logger.warning(f"TrendAgent failed/timed out: {e}")

        # Run FinAgent for specific ticker analysis (with timing)
        fin_agent = FinAgent(db=db, model=reasoning_model, tool_model=tool_model)
        signal = None

        step_start = time.time()
        try:
            signal = fin_agent.analyze_signal(f"分析 {ticker} 的最新市场动态和投资机会")
            if timing:
                timing.record_step("fin_agent", time.time() - step_start)
                logger.info(f"⏱️ FinAgent completed in {timing.step_times['fin_agent']:.1f}s")
        except Exception as e:
            if timing:
                timing.record_step("fin_agent", time.time() - step_start)
                timing.record_timeout("fin_agent")
            logger.warning(f"FinAgent failed/timed out: {e}")

        # Store timing stats
        if timing:
            self._last_timing_stats = timing
            logger.info(timing.summary())

        if signal:
            isq_score = ISQScore.from_investment_signal(signal)
            signal_type = isq_to_signal(isq_score)

            return {
                "signal": signal_type,
                "isq_score": isq_score.to_dict(),
                "overall_score": isq_score.calculate_overall_score(),
                "justification": signal.reasoning or signal.summary,
                "summary": signal.summary,
                "title": signal.title,
                "impact_tickers": getattr(signal, 'impact_tickers', []),
            }

        return self._mock_analyze_ticker(ticker, trading_date)

    def analyze_market(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        max_signals: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Analyze market hotspots using DeepEar's intelligence.

        Args:
            query: Analysis query (e.g., "A股半导体板块")
            sources: News sources to analyze
            max_signals: Maximum number of signals to return

        Returns:
            List of signal dictionaries with the same structure as analyze_ticker.
        """
        if not self.available:
            return [self._mock_analyze_ticker("market", datetime.now())]

        sources = sources or ["cls", "wallstreetcn", "xueqiu", "weibo"]

        try:
            from utils.database_manager import DatabaseManager
            from utils.llm.router import get_model_by_role
            from agents.trend_agent import TrendAgent

            db = DatabaseManager(db_path=self.db_path)
            reasoning_model = get_model_by_role("reasoning")
            tool_model = get_model_by_role("tool")

            trend_agent = TrendAgent(db=db, model=reasoning_model, tool_model=tool_model)
            result = trend_agent.discover_daily_signals(focus_sources=sources)

            # Parse results (simplified - in production, extract actual signals)
            return [{
                "signal": "Neutral",
                "isq_score": ISQScore(0.0, 0.5, 3, 0.5, 0.5).to_dict(),
                "overall_score": 0.5,
                "justification": "Market analysis completed",
                "summary": result.content if hasattr(result, 'content') else str(result),
            }]

        except Exception as e:
            logger.error(f"DeepEar market analysis failed: {e}")
            return [self._mock_analyze_ticker("market", datetime.now(), error=str(e))]

    def _mock_analyze_ticker(
        self,
        ticker: str,
        trading_date: Optional[datetime] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Mock analysis when DeepEar is not available.

        Returns a neutral signal with placeholder data.
        """
        if error:
            justification = f"DeepEar not available: {error}. Using default neutral stance."
        else:
            justification = "DeepEar integration not configured. Using default neutral stance."

        return {
            "signal": "Neutral",
            "isq_score": ISQScore(0.0, 0.5, 3, 0.5, 0.5).to_dict(),
            "overall_score": 0.5,
            "justification": justification,
            "summary": f"Mock analysis for {ticker}",
            "title": f"Analysis for {ticker}",
            "impact_tickers": [],
        }

    def is_available(self) -> bool:
        """Check if DeepEar integration is available."""
        return self.available
