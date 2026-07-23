"""
BaseAnalyst - Base class for all analysts in DeepFund

This class provides a unified interface and shared functionality for all analysts,
reducing code duplication and ensuring consistent behavior across all analysts.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from graph.schema import FundState, AnalystSignal
from graph.constants import Signal
from llm.inference import agent_call
from apis.router import Router, resolve_api_source
from util.db_helper import get_db
from util.logger import logger
from util.error_handler import (
    ErrorStats
)
from util.threshold_config import get_threshold_config


class BaseAnalyst(ABC):
    """
    Abstract base class for all analysts.

    Subclasses must implement:
        fetch_data(state: FundState, router: Router) -> Any
        build_prompt(data: Any) -> str
    """

    def __init__(self, agent_key: str, prompt_template: str, thresholds: Optional[Dict[str, Any]] = None):
        """
        Initialize the base analyst.

        Args:
            agent_key: Unique identifier for the analyst (from AgentKey)
            prompt_template: Prompt template string to use for this analyst
            thresholds: Optional thresholds dictionary. If None, loads from config
        """
        self.agent_key = agent_key
        self.prompt_template = prompt_template
        self.thresholds = thresholds or get_threshold_config().get_thresholds(agent_key)

    @abstractmethod
    def fetch_data(self, state: FundState, router: Router) -> Any:
        """
        Fetch data needed for analysis. Must be implemented by subclasses.

        Args:
            state: Current FundState
            router: Router instance for API calls

        Returns:
            Data object/structure needed for prompt building

        Raises:
            Exception: If data fetching fails
        """
        pass

    @abstractmethod
    def build_prompt(self, data: Any) -> str:
        """
        Build the prompt from fetched data. Must be implemented by subclasses.

        Args:
            data: Data returned from fetch_data()

        Returns:
            Formatted prompt string for LLM
        """
        pass

    def analyze(self, state: FundState) -> Dict[str, Any]:
        """
        Unified analysis workflow with consistent error handling.

        This method orchestrates the entire analysis process:
            1. Initialize database and router
            2. Fetch data via fetch_data()
            3. Build prompt via build_prompt()
            4. Call LLM via agent_call()
            5. Save results to database
            6. Return analyst signals

        All errors are caught and a NEUTRAL signal is returned instead of crashing.

        Args:
            state: Current FundState

        Returns:
            Dict with "analyst_signals" key containing the AnalystSignal
        """
        # Extract state information
        ticker = state["ticker"]
        llm_config = state["llm_config"]
        portfolio_id = state["portfolio"].id
        market = state.get("market", "us")
        skip_db_writes = bool(state.get("skip_db_writes", False))

        # Initialize database
        db = get_db()
        logger.log_agent_status(self.agent_key, ticker, "Fetching data")

        prefetched_analyst_data = state.get("prefetched_analyst_data", {})
        prefetched_payload = None
        if isinstance(prefetched_analyst_data, dict):
            prefetched_payload = prefetched_analyst_data.get(self.agent_key)

        if isinstance(prefetched_payload, dict) and "prompt_data" in prefetched_payload:
            data = prefetched_payload["prompt_data"]
        else:
            try:
                api_source = resolve_api_source(market, state.get("api_source"))
                router = Router(api_source)
                data = self.fetch_data(state, router)
            except Exception as e:
                error_msg = f"Failed to fetch data: {str(e)}"
                logger.error(f"[{self.agent_key}] {error_msg} for {ticker}")
                ErrorStats.record_error(self.agent_key, "data_fetch", str(e))
                return self._create_neutral_signal(
                    db, portfolio_id, ticker, error_msg, skip_db_writes=skip_db_writes
                )

        # Build prompt with error handling
        try:
            prompt = self.build_prompt(data)
        except Exception as e:
            error_msg = f"Failed to build prompt: {str(e)}"
            logger.error(f"[{self.agent_key}] {error_msg} for {ticker}")
            ErrorStats.record_error(self.agent_key, "data_validation", str(e))
            return self._create_neutral_signal(
                db, portfolio_id, ticker, error_msg, skip_db_writes=skip_db_writes
            )

        # Get LLM signal with error handling
        try:
            signal = agent_call(
                prompt=prompt,
                llm_config=llm_config,
                pydantic_model=AnalystSignal,
                agent_name=self.agent_key
            )
        except Exception as e:
            error_msg = f"LLM call failed: {str(e)}"
            logger.error(f"[{self.agent_key}] {error_msg} for {ticker}")
            ErrorStats.record_error(self.agent_key, "llm_call", str(e))
            return self._create_neutral_signal(
                db,
                portfolio_id,
                ticker,
                error_msg,
                prompt,
                skip_db_writes=skip_db_writes,
            )

        # Save signal
        logger.log_signal(self.agent_key, ticker, signal)
        if not skip_db_writes and db is not None:
            db.save_signal(portfolio_id, self.agent_key, ticker, prompt, signal)

        return {"analyst_signals": [signal]}

    def _create_neutral_signal(
        self,
        db,
        portfolio_id: str,
        ticker: str,
        justification: str,
        prompt: str = None,
        skip_db_writes: bool = False,
    ) -> Dict[str, Any]:
        """
        Create and save a neutral signal for error cases.

        Args:
            db: Database instance
            portfolio_id: Portfolio ID
            ticker: Ticker symbol
            justification: Error description
            prompt: Optional prompt that failed

        Returns:
            Dict with analyst_signals containing NEUTRAL signal
        """
        signal = AnalystSignal(
            signal=Signal.NEUTRAL,
            justification=f"[Error] {justification}"
        )

        logger.log_signal(self.agent_key, ticker, signal)

        if prompt is None:
            prompt = f"Error in {self.agent_key}: {justification}"

        if not skip_db_writes and db is not None:
            db.save_signal(portfolio_id, self.agent_key, ticker, prompt, signal)

        return {"analyst_signals": [signal]}
