"""
Unit tests for error handling utilities.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add paths
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

from deepfund.src.util.error_handler import (
    ErrorType,
    AnalystError,
    DataFetchError,
    APINetworkError,
    APIRateLimitError,
    LLMCallError,
    create_neutral_signal,
    retry_api_call,
    handle_analyst_errors,
    ErrorStats
)
from deepfund.src.graph.constants import Signal


class TestErrorTypes:
    """Test error type classifications."""

    def test_error_type_enum(self):
        """Test error type enum values."""
        assert ErrorType.DATA_FETCH.value == "data_fetch"
        assert ErrorType.API_NETWORK.value == "api_network"
        assert ErrorType.LLM_PROVIDER.value == "llm_provider"

    def test_analyst_error_creation(self):
        """Test creating an AnalystError."""
        error = AnalystError("Test error", ErrorType.DATA_FETCH, "test_analyst")
        assert str(error) == "Test error"
        assert error.error_type == ErrorType.DATA_FETCH
        assert error.analyst == "test_analyst"
        assert isinstance(error.timestamp, datetime)

    def test_data_fetch_error(self):
        """Test DataFetchError."""
        error = DataFetchError("Failed to fetch", "technical")
        assert error.error_type == ErrorType.DATA_FETCH
        assert error.analyst == "technical"

    def test_api_network_error(self):
        """Test APINetworkError."""
        error = APINetworkError("Network timeout", "fundamental")
        assert error.error_type == ErrorType.API_NETWORK

    def test_api_rate_limit_error(self):
        """Test APIRateLimitError."""
        error = APIRateLimitError("Rate limited", "company_news")
        assert error.error_type == ErrorType.API_RATE_LIMIT

    def test_llm_call_error(self):
        """Test LLMCallError."""
        error = LLMCallError("LLM timeout", "portfolio")
        assert error.error_type == ErrorType.LLM_PROVIDER


class TestNeutralSignal:
    """Test neutral signal creation."""

    def test_create_neutral_signal_basic(self):
        """Test creating a basic neutral signal."""
        result = create_neutral_signal("Test error")

        assert "analyst_signals" in result
        assert len(result["analyst_signals"]) == 1

        signal = result["analyst_signals"][0]
        assert signal.signal == Signal.NEUTRAL
        assert "Test error" in signal.justification

    def test_create_neutral_signal_with_analyst(self):
        """Test creating a neutral signal with analyst name."""
        result = create_neutral_signal("API failed", "technical")

        signal = result["analyst_signals"][0]
        assert signal.signal == Signal.NEUTRAL
        assert "[technical]" in signal.justification
        assert "API failed" in signal.justification


class TestRetryDecorator:
    """Test retry decorator functionality."""

    def test_retry_success_on_first_try(self):
        """Test that successful call doesn't retry."""
        call_count = 0

        @retry_api_call(max_retries=3)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_on_retryable_error(self):
        """Test retry on retryable errors."""
        call_count = 0

        @retry_api_call(max_retries=3, backoff_factor=0.1)
        def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise APINetworkError("Network error")
            return "success"

        result = failing_func()
        assert result == "success"
        assert call_count == 3

    def test_retry_exhausted(self):
        """Test that exception is raised after max retries."""
        call_count = 0

        @retry_api_call(max_retries=2, backoff_factor=0.1)
        def always_failing():
            nonlocal call_count
            call_count += 1
            raise APINetworkError("Always fails")

        with pytest.raises(AnalystError):
            always_failing()

        assert call_count == 2

    def test_non_retryable_error_immediate_raise(self):
        """Test that non-retryable errors raise immediately."""
        call_count = 0

        @retry_api_call(max_retries=3)
        def non_retryable_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")

        # Non-retryable errors should be wrapped in AnalystError
        with pytest.raises((AnalystError, ValueError)):
            non_retryable_error()

        assert call_count == 1


class TestHandleAnalystErrors:
    """Test analyst error handler decorator."""

    def setup_method(self):
        """Clear error stats before each test."""
        ErrorStats.clear()

    def test_successful_call_passthrough(self):
        """Test that successful calls pass through unchanged."""
        @handle_analyst_errors
        def successful_analyst(state):
            return {"analyst_signals": [{"signal": "BULLISH"}]}

        result = successful_analyst({"ticker": "AAPL"})
        assert result["analyst_signals"][0]["signal"] == "BULLISH"

    def test_analyst_error_returns_neutral(self):
        """Test that AnalystError returns neutral signal."""
        @handle_analyst_errors
        def failing_analyst(state):
            raise DataFetchError("Data not found", "test_analyst")

        result = failing_analyst({"ticker": "AAPL"})
        assert result["analyst_signals"][0].signal == Signal.NEUTRAL
        assert "Data not found" in result["analyst_signals"][0].justification

    def test_generic_error_returns_neutral(self):
        """Test that generic errors return neutral signal."""
        @handle_analyst_errors
        def crashing_analyst(state):
            raise ValueError("Unexpected error")

        result = crashing_analyst({"ticker": "AAPL"})
        assert result["analyst_signals"][0].signal == Signal.NEUTRAL
        assert "Unexpected error" in result["analyst_signals"][0].justification

    def test_error_stats_recorded(self):
        """Test that errors are recorded in stats."""
        ErrorStats.clear()

        @handle_analyst_errors
        def failing_analyst(state):
            raise DataFetchError("Test error", "test_analyst")

        failing_analyst({"ticker": "AAPL"})

        stats = ErrorStats.get_stats()
        assert stats["total_errors"] == 1


class TestErrorStats:
    """Test error statistics tracking."""

    def setup_method(self):
        """Clear error stats before each test."""
        ErrorStats.clear()

    def test_record_error(self):
        """Test recording an error."""
        ErrorStats.record_error("technical", "data_fetch", "Test error")

        stats = ErrorStats.get_stats()
        assert stats["total_errors"] == 1
        assert stats["error_counts"]["data_fetch"] == 1

    def test_multiple_errors(self):
        """Test recording multiple errors."""
        ErrorStats.record_error("technical", "data_fetch", "Error 1")
        ErrorStats.record_error("fundamental", "api_network", "Error 2")
        ErrorStats.record_error("technical", "llm_call", "Error 3")

        stats = ErrorStats.get_stats()
        assert stats["total_errors"] == 3
        assert stats["analysts_with_errors"] == 2  # technical and fundamental

    def test_clear_stats(self):
        """Test clearing statistics."""
        ErrorStats.record_error("test", "test_type", "Test")
        ErrorStats.clear()

        stats = ErrorStats.get_stats()
        assert stats["total_errors"] == 0

    def test_error_limit_per_analyst(self):
        """Test that error history is limited per analyst."""
        # Record more than 100 errors
        for i in range(150):
            ErrorStats.record_error("test_analyst", "test_type", f"Error {i}")

        stats = ErrorStats.get_stats()
        # Should only keep last 100 in errors_by_analyst, but recent_errors shows last 10
        assert len(stats["recent_errors"]["test_analyst"]) == 10


class TestIntegration:
    """Integration tests for error handling."""

    def setup_method(self):
        """Clear error stats before each test."""
        ErrorStats.clear()

    def test_full_error_flow(self):
        """Test complete error handling flow."""
        @handle_analyst_errors
        @retry_api_call(max_retries=2, backoff_factor=0.1)
        def api_calling_analyst(state):
            if state.get("fail"):
                raise APINetworkError("Network failed", "test")
            return {"analyst_signals": [{"signal": "BULLISH"}]}

        # Success case
        result = api_calling_analyst({"ticker": "AAPL", "fail": False})
        assert result["analyst_signals"][0]["signal"] == "BULLISH"

        # Failure case after retries
        result = api_calling_analyst({"ticker": "AAPL", "fail": True})
        assert result["analyst_signals"][0].signal == Signal.NEUTRAL

    def test_error_stats_accumulation(self):
        """Test that errors accumulate across multiple analysts."""
        @handle_analyst_errors
        def analyst1(state):
            raise DataFetchError("Error 1", "analyst1")

        @handle_analyst_errors
        def analyst2(state):
            raise LLMCallError("Error 2", "analyst2")

        analyst1({"ticker": "AAPL"})
        analyst2({"ticker": "MSFT"})

        stats = ErrorStats.get_stats()
        assert stats["total_errors"] == 2
        assert stats["analysts_with_errors"] == 2  # analyst1 and analyst2
