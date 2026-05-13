"""
Unit tests for Portfolio Manager functionality.

Tests the core trading decision logic, risk control,
and share calculation functions.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

# Add paths
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

from deepfund.src.agents.portfolio_manager import (
    portfolio_agent,
    format_analyst_signals_summary,
    calculate_ticker_shares,
    resolve_max_position_ratio,
    thresholds
)
from deepfund.src.graph.schema import FundState, Portfolio, Position, Decision, AnalystSignal, PositionRisk
from deepfund.src.graph.constants import AgentKey, Action, Signal


def create_test_state(
    ticker: str = "AAPL",
    trading_date: str = "2024-01-15",
    analyst_signals: list = None,
    portfolio_cashflow: float = 100000.0,
    positions: dict = None,
    personality: str = "balanced",
    num_tickers: int = 1,
    market: str = "cn"
) -> FundState:
    """Create a test FundState for testing."""
    if analyst_signals is None:
        analyst_signals = []
    if positions is None:
        positions = {}

    portfolio = Portfolio(
        id="test-portfolio-id",
        cashflow=portfolio_cashflow,
        positions=positions
    )

    return FundState(
        ticker=ticker,
        trading_date=trading_date,
        exp_name="test-experiment",
        portfolio=portfolio,
        analyst_signals=analyst_signals,
        llm_config={"provider": "test", "model": "test-model"},
        personality=personality,
        num_tickers=num_tickers,
        market=market
    )


class TestFormatAnalystSignalsSummary:
    """Test the analyst signals summary formatting."""

    def test_empty_signals(self):
        """Test with empty signals list."""
        result = format_analyst_signals_summary([])
        assert result == "No analyst signals available."

    def test_none_signals(self):
        """Test with None signals."""
        result = format_analyst_signals_summary(None)
        assert result == "No analyst signals available."

    def test_single_analyst_signal(self):
        """Test with a single AnalystSignal object."""
        signal = AnalystSignal(
            signal=Signal.BULLISH,
            justification="Strong fundamentals"
        )
        result = format_analyst_signals_summary([signal])

        assert "Signal 1:" in result
        assert "Bullish" in result  # Signal.BULLISH.value is "Bullish"
        assert "Strong fundamentals" in result

    def test_multiple_analyst_signals(self):
        """Test with multiple AnalystSignal objects."""
        signals = [
            AnalystSignal(signal=Signal.BULLISH, justification="Good earnings"),
            AnalystSignal(signal=Signal.BEARISH, justification="High valuation")
        ]
        result = format_analyst_signals_summary(signals)

        assert "Signal 1:" in result
        assert "Signal 2:" in result
        assert "Bullish" in result
        assert "Bearish" in result

    def test_dict_format_signals(self):
        """Test with dict format signals."""
        signals = [
            {"signal": "Bullish", "justification": "Dict signal"}
        ]
        result = format_analyst_signals_summary(signals)

        assert "Signal 1:" in result
        assert "Bullish" in result

    def test_mixed_format_signals(self):
        """Test with mixed format signals."""
        signals = [
            AnalystSignal(signal=Signal.NEUTRAL, justification="Object signal"),
            {"signal": "Bullish", "justification": "Dict signal"}
        ]
        result = format_analyst_signals_summary(signals)

        assert "Signal 1:" in result
        assert "Signal 2:" in result


class TestCalculateTickerShares:
    """Test the share calculation logic."""

    def test_no_position_buy(self):
        """Test buying when no position exists."""
        portfolio = Portfolio(
            id="test",
            cashflow=100000.0,
            positions={}
        )
        current_price = 100.0
        ticker = "AAPL"
        optimal_ratio = 0.2  # 20% of portfolio

        current_shares, tradable_shares = calculate_ticker_shares(
            portfolio, current_price, ticker, optimal_ratio
        )

        assert current_shares == 0
        # 20% of 100000 = 20000, at 100 per share = 200 shares
        assert tradable_shares == 200

    def test_existing_position_buy_more(self):
        """Test buying more when already have position."""
        portfolio = Portfolio(
            id="test",
            cashflow=50000.0,
            positions={"AAPL": Position(ticker="AAPL", shares=50, value=5000)}
        )
        current_price = 100.0
        ticker = "AAPL"
        optimal_ratio = 0.2

        current_shares, tradable_shares = calculate_ticker_shares(
            portfolio, current_price, ticker, optimal_ratio
        )

        assert current_shares == 50
        # Can buy more shares
        assert tradable_shares > 0

    def test_position_above_optimal_sell(self):
        """Test selling when position exceeds optimal."""
        portfolio = Portfolio(
            id="test",
            cashflow=10000.0,
            positions={"AAPL": Position(ticker="AAPL", shares=100, value=10000)}
        )
        current_price = 100.0
        ticker = "AAPL"
        optimal_ratio = 0.05

        current_shares, tradable_shares = calculate_ticker_shares(
            portfolio, current_price, ticker, optimal_ratio
        )

        assert current_shares == 100
        # Should be negative (sell)
        assert tradable_shares < 0

    def test_zero_optimal_ratio(self):
        """Test with zero optimal ratio."""
        portfolio = Portfolio(
            id="test",
            cashflow=100000.0,
            positions={"AAPL": Position(ticker="AAPL", shares=50, value=5000)}
        )
        current_price = 100.0
        ticker = "AAPL"
        optimal_ratio = 0.0

        current_shares, tradable_shares = calculate_ticker_shares(
            portfolio, current_price, ticker, optimal_ratio
        )

        assert current_shares == 50
        # Should sell all shares
        assert tradable_shares == -50


class TestPortfolioAgent:
    """Test the main portfolio agent function."""

    @patch('deepfund.src.agents.portfolio_manager.Router')
    @patch('deepfund.src.agents.portfolio_manager.agent_call')
    @patch('deepfund.src.agents.portfolio_manager.get_db')
    def test_successful_buy_decision(
        self, mock_get_db, mock_agent_call, mock_router_class
    ):
        """Test successful buy decision flow."""
        # Setup mocks
        mock_db = Mock()
        mock_db.get_decision_memory.return_value = []
        mock_db.save_decision = Mock()
        mock_get_db.return_value = mock_db

        # Mock Router to return float price
        mock_router = Mock()
        mock_router.get_cn_stock_last_close_price = Mock(return_value=100.0)
        mock_router_class.return_value = mock_router

        # Mock LLM responses
        def agent_call_side_effect(prompt, llm_config, pydantic_model, agent_name):
            if agent_name == "risk_control":
                return PositionRisk(
                    optimal_position_ratio=0.2,
                    justification="Test risk assessment"
                )
            elif agent_name == "portfolio_manager":
                return Decision(
                    action=Action.BUY,
                    shares=10,
                    price=100.0,
                    reasoning="Test buy decision"
                )
            return None

        mock_agent_call.side_effect = agent_call_side_effect

        # Create test state
        bullish_signal = AnalystSignal(signal=Signal.BULLISH, justification="Test")
        state = create_test_state(analyst_signals=[bullish_signal], market="cn")

        # Execute
        result = portfolio_agent(state)

        # Verify
        assert "decision" in result
        assert result["decision"].action == Action.BUY
        assert result["decision"].shares == 10

    @patch('deepfund.src.agents.portfolio_manager.Router')
    @patch('deepfund.src.agents.portfolio_manager.agent_call')
    @patch('deepfund.src.agents.portfolio_manager.get_db')
    def test_sell_decision(
        self, mock_get_db, mock_agent_call, mock_router_class
    ):
        """Test sell decision flow."""
        # Setup mocks
        mock_db = Mock()
        mock_db.get_decision_memory.return_value = []
        mock_db.save_decision = Mock()
        mock_get_db.return_value = mock_db

        mock_router = Mock()
        mock_router.get_cn_stock_last_close_price = Mock(return_value=100.0)
        mock_router_class.return_value = mock_router

        def agent_call_side_effect(prompt, llm_config, pydantic_model, agent_name):
            if agent_name == "risk_control":
                return PositionRisk(
                    optimal_position_ratio=0.0,
                    justification="Reduce position"
                )
            elif agent_name == "portfolio_manager":
                return Decision(
                    action=Action.SELL,
                    shares=5,
                    price=100.0,
                    reasoning="Test sell decision"
                )
            return None

        mock_agent_call.side_effect = agent_call_side_effect

        bearish_signal = AnalystSignal(signal=Signal.BEARISH, justification="Test")
        state = create_test_state(analyst_signals=[bearish_signal], market="cn")

        result = portfolio_agent(state)

        assert result["decision"].action == Action.SELL

    @patch('deepfund.src.agents.portfolio_manager.Router')
    @patch('deepfund.src.agents.portfolio_manager.get_db')
    def test_price_fetch_error(self, mock_get_db, mock_router_class):
        """Test error handling when price fetch fails."""
        mock_db = Mock()
        mock_get_db.return_value = mock_db

        mock_router = Mock()
        mock_router.get_cn_stock_last_close_price = Mock(side_effect=Exception("API Error"))
        mock_router_class.return_value = mock_router

        state = create_test_state(market="cn")

        with pytest.raises(RuntimeError, match="Failed to make decision"):
            portfolio_agent(state)


class TestThresholds:
    """Test threshold configurations."""

    def test_decision_memory_limit_exists(self):
        """Test that decision memory limit is configured."""
        assert "decision_memory_limit" in thresholds
        assert thresholds["decision_memory_limit"] == 5


class TestPositionRatioClamping:
    """Test position ratio clamping logic."""

    @patch('deepfund.src.agents.portfolio_manager.Router')
    @patch('deepfund.src.agents.portfolio_manager.agent_call')
    @patch('deepfund.src.agents.portfolio_manager.get_db')
    def test_position_ratio_clamped_to_max(
        self, mock_get_db, mock_agent_call, mock_router_class
    ):
        """Test that position ratio is clamped to max_position_ratio."""
        mock_db = Mock()
        mock_db.get_decision_memory.return_value = []
        mock_db.save_decision = Mock()
        mock_get_db.return_value = mock_db

        mock_router = Mock()
        mock_router.get_cn_stock_last_close_price = Mock(return_value=100.0)
        mock_router_class.return_value = mock_router

        def agent_call_side_effect(prompt, llm_config, pydantic_model, agent_name):
            if agent_name == "risk_control":
                # Return ratio higher than max
                return PositionRisk(
                    optimal_position_ratio=2.0,  # 200%, should be clamped to 1.0
                    justification="Too bullish"
                )
            elif agent_name == "portfolio_manager":
                return Decision(
                    action=Action.HOLD,
                    shares=0,
                    price=100.0,
                    reasoning="Test"
                )
            return None

        mock_agent_call.side_effect = agent_call_side_effect

        state = create_test_state(num_tickers=1, market="cn")

        result = portfolio_agent(state)
        assert "decision" in result

    @patch('deepfund.src.agents.portfolio_manager.Router')
    @patch('deepfund.src.agents.portfolio_manager.agent_call')
    @patch('deepfund.src.agents.portfolio_manager.get_db')
    def test_position_ratio_clamped_to_zero(
        self, mock_get_db, mock_agent_call, mock_router_class
    ):
        """Test that negative position ratio is clamped to 0."""
        mock_db = Mock()
        mock_db.get_decision_memory.return_value = []
        mock_db.save_decision = Mock()
        mock_get_db.return_value = mock_db

        mock_router = Mock()
        mock_router.get_cn_stock_last_close_price = Mock(return_value=100.0)
        mock_router_class.return_value = mock_router

        def agent_call_side_effect(prompt, llm_config, pydantic_model, agent_name):
            if agent_name == "risk_control":
                return PositionRisk(
                    optimal_position_ratio=-0.5,  # Negative, should be clamped to 0
                    justification="Too bearish"
                )
            elif agent_name == "portfolio_manager":
                return Decision(
                    action=Action.HOLD,
                    shares=0,
                    price=100.0,
                    reasoning="Test"
                )
            return None

        mock_agent_call.side_effect = agent_call_side_effect

        state = create_test_state(market="cn")

        result = portfolio_agent(state)
        assert "decision" in result


class TestDecisionPostProcessing:
    """Test decision post-processing logic."""

    @patch('deepfund.src.agents.portfolio_manager.Router')
    @patch('deepfund.src.agents.portfolio_manager.agent_call')
    @patch('deepfund.src.agents.portfolio_manager.get_db')
    def test_negative_shares_corrected(
        self, mock_get_db, mock_agent_call, mock_router_class
    ):
        """Test that negative shares with SELL action are corrected."""
        mock_db = Mock()
        mock_db.get_decision_memory.return_value = []
        mock_db.save_decision = Mock()
        mock_get_db.return_value = mock_db

        mock_router = Mock()
        mock_router.get_cn_stock_last_close_price = Mock(return_value=100.0)
        mock_router_class.return_value = mock_router

        def agent_call_side_effect(prompt, llm_config, pydantic_model, agent_name):
            if agent_name == "risk_control":
                return PositionRisk(
                    optimal_position_ratio=0.1,
                    justification="Test"
                )
            elif agent_name == "portfolio_manager":
                # Return negative shares with SELL
                return Decision(
                    action=Action.SELL,
                    shares=-10,  # Negative
                    price=100.0,
                    reasoning="Test"
                )
            return None

        mock_agent_call.side_effect = agent_call_side_effect

        state = create_test_state(market="cn")
        result = portfolio_agent(state)

        # Shares should be corrected to positive
        assert result["decision"].shares == 10

    @patch('deepfund.src.agents.portfolio_manager.Router')
    @patch('deepfund.src.agents.portfolio_manager.agent_call')
    @patch('deepfund.src.agents.portfolio_manager.get_db')
    def test_price_overridden_with_current(
        self, mock_get_db, mock_agent_call, mock_router_class
    ):
        """Test that decision price is overridden with current price."""
        mock_db = Mock()
        mock_db.get_decision_memory.return_value = []
        mock_db.save_decision = Mock()
        mock_get_db.return_value = mock_db

        mock_router = Mock()
        mock_router.get_cn_stock_last_close_price = Mock(return_value=150.0)
        mock_router_class.return_value = mock_router

        def agent_call_side_effect(prompt, llm_config, pydantic_model, agent_name):
            if agent_name == "risk_control":
                return PositionRisk(
                    optimal_position_ratio=0.1,
                    justification="Test"
                )
            elif agent_name == "portfolio_manager":
                return Decision(
                    action=Action.BUY,
                    shares=5,
                    price=100.0,  # Different from current price
                    reasoning="Test"
                )
            return None

        mock_agent_call.side_effect = agent_call_side_effect

        state = create_test_state(market="cn")
        result = portfolio_agent(state)

        # Price should be overridden to current price
        assert result["decision"].price == 150.0


class TestPersonalityPositionCaps:
    """Test personality-aware position sizing caps."""

    def test_resolve_max_position_ratio_uses_personality_cap_for_fof(self):
        """FOF should keep its tighter sleeve-oriented per-name cap."""
        assert resolve_max_position_ratio("fof", 3) == 0.15

    def test_resolve_max_position_ratio_uses_diversification_cap_when_tighter(self):
        """Large baskets should still respect the tighter diversification cap."""
        assert resolve_max_position_ratio("balanced", 50) == 0.05

    @patch('deepfund.src.agents.portfolio_manager.Router')
    @patch('deepfund.src.agents.portfolio_manager.agent_call')
    @patch('deepfund.src.agents.portfolio_manager.get_db')
    def test_fof_prompt_uses_personality_position_cap(
        self, mock_get_db, mock_agent_call, mock_router_class
    ):
        """FOF risk prompts should expose the tighter 0.15 cap to the agent."""
        mock_db = Mock()
        mock_db.get_decision_memory.return_value = []
        mock_db.save_decision = Mock()
        mock_get_db.return_value = mock_db

        mock_router = Mock()
        mock_router.get_cn_stock_last_close_price = Mock(return_value=100.0)
        mock_router_class.return_value = mock_router

        captured = {}

        def agent_call_side_effect(prompt, llm_config, pydantic_model, agent_name):
            if agent_name == "risk_control":
                captured["risk_prompt"] = prompt
                return PositionRisk(
                    optimal_position_ratio=0.4,
                    justification="Too concentrated for FOF"
                )
            if agent_name == "portfolio_manager":
                captured["portfolio_prompt"] = prompt
                return Decision(
                    action=Action.HOLD,
                    shares=0,
                    price=100.0,
                    reasoning="Test"
                )
            return None

        mock_agent_call.side_effect = agent_call_side_effect

        state = create_test_state(personality="fof", num_tickers=3, market="cn")
        result = portfolio_agent(state)

        assert "decision" in result
        assert "[0, 0.15]" in captured["risk_prompt"]
        assert "Optimal Position Ratio: 0.15" in captured["portfolio_prompt"]
