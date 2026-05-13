"""
Unit tests for BaseAnalyst and migrated analysts

Tests the BaseAnalyst base class and verifies that migrated analysts
produce the same results as the original implementations.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add paths
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

from deepfund.src.agents.analysts.base import BaseAnalyst
from deepfund.src.graph.schema import FundState, Portfolio, Position, AnalystSignal
from deepfund.src.graph.constants import AgentKey, Signal
from deepfund.src.apis.router import Router


def create_test_state(ticker="600519", market="cn") -> FundState:
    """Create a test FundState"""
    return FundState(
        ticker=ticker,
        exp_name="test_exp",
        trading_date=datetime(2024, 1, 15),
        market=market,
        llm_config={
            "provider": "test",
            "model": "test-model",
            "temperature": 0.5
        },
        portfolio=Portfolio(
            id="test_portfolio_123",
            cashflow=100000.0,
            positions={}
        ),
        num_tickers=1,
        personality="balanced",
        analyst_signals=[],
        decision=None
    )


class TestBaseAnalyst:
    """Test BaseAnalyst abstract class"""

    def test_cannot_instantiate_base_class(self):
        """BaseAnalyst should not be instantiable directly"""
        with pytest.raises(TypeError):
            BaseAnalyst(AgentKey.FUNDAMENTAL, "test prompt")

    def test_subclass_must_implement_abstract_methods(self):
        """Subclass must implement fetch_data and build_prompt"""
        class IncompleteAnalyst(BaseAnalyst):
            pass

        with pytest.raises(TypeError):
            IncompleteAnalyst(AgentKey.FUNDAMENTAL, "test")


class ConcreteAnalyst(BaseAnalyst):
    """Concrete implementation for testing"""

    def fetch_data(self, state: FundState, router: Router):
        return {"test": "data"}

    def build_prompt(self, data):
        return f"Test prompt with {data}"


class TestConcreteAnalyst:
    """Test concrete implementation"""

    @patch('deepfund.src.agents.analysts.base.get_db')
    @patch('deepfund.src.agents.analysts.base.agent_call')
    @patch('deepfund.src.agents.analysts.base.Router')
    def test_analyze_success(self, mock_router_class, mock_agent_call, mock_get_db):
        """Test successful analysis flow"""
        # Setup mocks
        mock_db = Mock()
        mock_get_db.return_value = mock_db

        mock_signal = AnalystSignal(
            signal=Signal.BULLISH,
            justification="Test justification"
        )
        mock_agent_call.return_value = mock_signal

        # Create analyst and run
        analyst = ConcreteAnalyst(AgentKey.FUNDAMENTAL, "test template")
        state = create_test_state()
        result = analyst.analyze(state)

        # Verify
        assert "analyst_signals" in result
        assert len(result["analyst_signals"]) == 1
        assert result["analyst_signals"][0].signal == Signal.BULLISH

        # Verify agent_call was called correctly
        mock_agent_call.assert_called_once()
        call_args = mock_agent_call.call_args
        assert call_args[1]["agent_name"] == AgentKey.FUNDAMENTAL
        assert call_args[1]["pydantic_model"].__name__ == "AnalystSignal"

        # Verify db.save_signal was called
        mock_db.save_signal.assert_called_once()

    @patch('deepfund.src.agents.analysts.base.get_db')
    @patch('deepfund.src.agents.analysts.base.agent_call')
    @patch('deepfund.src.agents.analysts.base.Router')
    def test_analyze_fetch_error(self, mock_router_class, mock_agent_call, mock_get_db):
        """Test error handling when data fetch fails"""
        # Setup mocks
        mock_db = Mock()
        mock_get_db.return_value = mock_db

        # Create analyst that raises error in fetch_data
        class ErrorAnalyst(BaseAnalyst):
            def fetch_data(self, state, router):
                raise Exception("API Error")

            def build_prompt(self, data):
                return "test"

        analyst = ErrorAnalyst(AgentKey.FUNDAMENTAL, "test")
        state = create_test_state()
        result = analyst.analyze(state)

        # Should return NEUTRAL signal on error (not empty dict)
        assert "analyst_signals" in result
        assert len(result["analyst_signals"]) == 1
        assert result["analyst_signals"][0].signal == Signal.NEUTRAL
        assert "API Error" in result["analyst_signals"][0].justification

        # agent_call should not be called
        mock_agent_call.assert_not_called()

        # db.save_signal should still be called with the error signal
        mock_db.save_signal.assert_called_once()

    @patch('deepfund.src.agents.analysts.base.get_db')
    @patch('deepfund.src.agents.analysts.base.agent_call')
    @patch('deepfund.src.agents.analysts.base.Router')
    def test_analyze_skip_db_writes(self, mock_router_class, mock_agent_call, mock_get_db):
        """Test skip_db_writes mode avoids signal persistence."""
        mock_db = Mock()
        mock_get_db.return_value = mock_db

        mock_signal = AnalystSignal(
            signal=Signal.BULLISH,
            justification="Skip DB writes in signal collection phase"
        )
        mock_agent_call.return_value = mock_signal

        analyst = ConcreteAnalyst(AgentKey.FUNDAMENTAL, "test template")
        state = create_test_state()
        state["skip_db_writes"] = True
        result = analyst.analyze(state)

        assert "analyst_signals" in result
        assert len(result["analyst_signals"]) == 1
        assert result["analyst_signals"][0].signal == Signal.BULLISH

        mock_db.save_signal.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
