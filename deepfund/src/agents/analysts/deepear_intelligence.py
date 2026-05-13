"""
DeepEar Intelligence Analyst - Refactored to use BaseAnalyst

Uses DeepEar's ISQ framework for intelligence analysis.
This analyst integrates with DeepEar's multi-agent financial intelligence system,
providing ISQ-based signal quality assessment for A-share market opportunities.
"""

from typing import Any
from graph.schema import FundState, AnalystSignal
from graph.constants import AgentKey, Signal
from apis.router import Router
from util.logger import logger
from util.db_helper import get_db
from .base import BaseAnalyst

# Import DeepEar client
try:
    from integrations.deepear_client import DeepEarClient, isq_to_signal
except ImportError:
    from integrations.deepear_client import DeepEarClient, isq_to_signal


# Analyst prompt template (for reference, not used in LLM call)
DEEPEAR_INTELLIGENCE_PROMPT = """
You are a DeepEar Intelligence Analyst specializing in A-share market intelligence
using the ISQ (Investment Signal Quality) framework.

DeepEar has provided the following intelligence analysis for ticker {ticker}:

Intelligence Summary:
{summary}

Signal: {signal}

ISQ Scores:
- Sentiment: {sentiment:.2f} (-1.0 = Extremely Bearish, 0.0 = Neutral, 1.0 = Extremely Bullish)
- Confidence: {confidence:.2f} (0.0 = Low Certainty, 1.0 = High Certainty)
- Intensity: {intensity}/5 (Impact magnitude)
- Expectation Gap: {expectation_gap:.2f} (0.0 = Fully Priced, 1.0 = Huge Expectation Gap)
- Timeliness: {timeliness:.2f} (0.0 = Long-term, 1.0 = Immediate)

Overall ISQ Score: {overall_score:.2f} (0.0 = Poor, 1.0 = Excellent)

Justification:
{justification}

Based on this ISQ intelligence analysis, provide your structured output with:
- signal: One of ["Bullish", "Bearish", "Neutral"]
- justification: A brief explanation incorporating the ISQ assessment

Consider:
1. High confidence (>0.7) combined with strong sentiment (>0.3 or <-0.3) indicates reliable signals
2. High intensity (4-5) means significant market impact expected
3. Large expectation gap (>0.6) suggests mispricing opportunities
4. High timeliness (>0.8) indicates immediate action may be warranted
"""


class DeepEarIntelligenceAnalyst(BaseAnalyst):
    """
    DeepEar Intelligence Analyst using ISQ framework for signal quality assessment.
    This analyst leverages DeepEar's multi-agent intelligence system to provide
    ISQ-based investment signals for A-share market opportunities.

    Note: This analyst overrides analyze() because it doesn't call LLM -
    DeepEar already provides structured signals.
    """

    def __init__(self):
        # Note: We don't use the prompt template for LLM call,
        # but initialize it for consistency with BaseAnalyst interface
        super().__init__(AgentKey.DEEPEAR_INTELLIGENCE, DEEPEAR_INTELLIGENCE_PROMPT)

    def fetch_data(self, state: FundState, router: Router) -> Any:
        """
        Fetch DeepEar intelligence analysis for the ticker.

        Args:
            state: Current FundState
            router: Router instance (not used, uses DeepEarClient directly)

        Returns:
            Dict with DeepEar analysis result
        """
        ticker = state["ticker"]
        trading_date = state["trading_date"]

        # Check if running in backtest mode (skip polymarket for speed)
        is_backtest = state.get("is_backtest", False)

        # Initialize DeepEar client
        client = DeepEarClient(skip_polymarket=is_backtest, enable_timing=True)

        if not client.is_available():
            return {"available": False, "error": "DeepEar not available"}

        # Run DeepEar analysis
        analysis_result = client.analyze_ticker(
            ticker=ticker,
            trading_date=trading_date,
            sources=["cls", "wallstreetcn", "xueqiu"]
        )

        return {
            "available": True,
            "result": analysis_result
        }

    def build_prompt(self, data: Any) -> str:
        """
        Build prompt from DeepEar analysis data (for logging purposes).

        Args:
            data: Dict with DeepEar analysis result

        Returns:
            Formatted prompt string for reference
        """
        if not data.get("available"):
            return "DeepEar not available"

        result = data["result"]
        isq_score = result.get("isq_score", {})

        return self.prompt_template.format(
            ticker=result.get("ticker", "unknown"),
            summary=result.get("summary", ""),
            signal=result.get("signal", "Neutral"),
            sentiment=isq_score.get("sentiment", 0),
            confidence=isq_score.get("confidence", 0.5),
            intensity=isq_score.get("intensity", 3),
            expectation_gap=isq_score.get("expectation_gap", 0.5),
            timeliness=isq_score.get("timeliness", 0.5),
            overall_score=result.get("overall_score", 0.5),
            justification=result.get("justification", "")
        )

    def analyze(self, state: FundState) -> dict:
        """
        Override analyze() to skip LLM call - DeepEar provides structured signals directly.

        Args:
            state: Current FundState

        Returns:
            Dict with analyst_signals
        """
        ticker = state["ticker"]
        portfolio_id = state["portfolio"].id
        skip_db_writes = bool(state.get("skip_db_writes", False))
        db = get_db()

        logger.log_agent_status(self.agent_key, ticker, "Running DeepEar intelligence analysis")

        # Get API source and router (needed for BaseAnalyst interface)
        market = state.get("market", "us")
        from apis.router import resolve_api_source
        # Fetch data
        try:
            api_source = resolve_api_source(market, state.get("api_source"))
            router = Router(api_source)
            data = self.fetch_data(state, router)
        except Exception as e:
            logger.error(f"Failed to fetch DeepEar data for {ticker}: {e}")
            return self._fallback_signal(ticker, portfolio_id, db, str(e), skip_db_writes)

        # Check if DeepEar is available
        if not data.get("available"):
            return self._fallback_signal(
                ticker, portfolio_id, db,
                "DeepEar intelligence system not available. Recommend neutral stance.",
                skip_db_writes,
            )

        # Extract result
        result = data["result"]
        isq_score = result.get("isq_score", {})
        signal_type_str = result.get("signal", "Neutral")

        # Convert string to Signal enum
        signal_type = Signal.NEUTRAL
        if signal_type_str == "Bullish":
            signal_type = Signal.BULLISH
        elif signal_type_str == "Bearish":
            signal_type = Signal.BEARISH

        # Build enhanced justification with ISQ details
        isq_details = (
            f"ISQ Analysis: Sentiment={isq_score.get('sentiment', 0):.2f}, "
            f"Confidence={isq_score.get('confidence', 0.5):.2f}, "
            f"Intensity={isq_score.get('intensity', 3)}/5, "
            f"Expectation Gap={isq_score.get('expectation_gap', 0.5):.2f}, "
            f"Timeliness={isq_score.get('timeliness', 0.5):.2f}, "
            f"Overall Score={result.get('overall_score', 0.5):.2f}. "
            f"{result.get('justification', '')}"
        )

        # Create analyst signal
        signal = AnalystSignal(
            signal=signal_type,
            justification=isq_details
        )

        # Log timing stats if available
        timing = result.get("timing")
        if timing:
            logger.info(f"DeepEar timing for {ticker}: {timing}")

        # Log and save signal
        logger.log_signal(self.agent_key, ticker, signal)
        prompt = self.build_prompt(data)
        if not skip_db_writes and db is not None:
            db.save_signal(
                portfolio_id,
                self.agent_key,
                ticker,
                prompt,
                signal
            )

        return {"analyst_signals": [signal]}

    def _fallback_signal(
        self,
        ticker: str,
        portfolio_id: str,
        db,
        justification: str,
        skip_db_writes: bool = False,
    ) -> dict:
        """Return a neutral fallback signal when DeepEar fails."""
        signal = AnalystSignal(
            signal=Signal.NEUTRAL,
            justification=justification
        )
        logger.log_signal(self.agent_key, ticker, signal)
        if not skip_db_writes and db is not None:
            db.save_signal(
                portfolio_id,
                self.agent_key,
                ticker,
                f"DeepEar error: {justification}",
                signal
            )
        return {"analyst_signals": [signal]}


# Backward-compatible function interface
def deepear_intelligence_agent(state: FundState):
    """
    DeepEar Intelligence Analyst function (backward compatible).

    Args:
        state: Current FundState

    Returns:
        Dict with analyst_signals
    """
    return DeepEarIntelligenceAnalyst().analyze(state)
