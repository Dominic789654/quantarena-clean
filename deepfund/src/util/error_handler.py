"""
Error handling utilities for DeepFund analysts.

This module provides unified error handling and retry mechanisms
for all analysts in the DeepFund system.
"""

import time
import functools
from typing import Any, Callable, Optional, Type, Dict, List
from datetime import datetime
from collections import defaultdict
from enum import Enum

from graph.schema import AnalystSignal
from graph.constants import Signal
from util.logger import logger


class ErrorType(Enum):
    """Error types for classification."""
    API_NETWORK = "api_network"
    API_RATE_LIMIT = "api_rate_limit"
    API_DATA_ERROR = "api_data_error"
    LLM_TIMEOUT = "llm_timeout"
    LLM_PROVIDER = "llm_provider"
    DATA_FETCH = "data_fetch"
    DATA_VALIDATION = "data_validation"
    UNKNOWN = "unknown"


class AnalystError(Exception):
    """Base exception for analyst errors."""
    def __init__(self, message: str, error_type: ErrorType, analyst: str = None):
        super().__init__(message)
        self.error_type = error_type
        self.analyst = analyst
        self.timestamp = datetime.now()


class DataFetchError(AnalystError):
    """Exception for data fetching failures."""
    def __init__(self, message: str, analyst: str = None):
        super().__init__(message, ErrorType.DATA_FETCH, analyst)


class APINetworkError(AnalystError):
    """Exception for API network failures."""
    def __init__(self, message: str, analyst: str = None):
        super().__init__(message, ErrorType.API_NETWORK, analyst)


class APIRateLimitError(AnalystError):
    """Exception for API rate limiting."""
    def __init__(self, message: str, analyst: str = None):
        super().__init__(message, ErrorType.API_RATE_LIMIT, analyst)


class LLMCallError(AnalystError):
    """Exception for LLM call failures."""
    def __init__(self, message: str, analyst: str = None):
        super().__init__(message, ErrorType.LLM_PROVIDER, analyst)


def create_neutral_signal(justification: str, analyst: str = None) -> Dict[str, Any]:
    """
    Create a neutral signal with error justification.

    Args:
        justification: Error description
        analyst: Analyst name (optional)

    Returns:
        Dict with analyst_signals containing a NEUTRAL signal
    """
    if analyst:
        justification = f"[{analyst}] {justification}"

    signal = AnalystSignal(
        signal=Signal.NEUTRAL,
        justification=justification
    )

    return {"analyst_signals": [signal]}


def retry_api_call(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    jitter: float = 0.1,
    retryable_errors: Optional[List[Type[Exception]]] = None
):
    """
    Decorator for retrying API calls with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for backoff time
        jitter: Random jitter factor (0-1)
        retryable_errors: List of exception types to retry
    """
    if retryable_errors is None:
        retryable_errors = [APINetworkError, APIRateLimitError, ConnectionError, TimeoutError]

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            analyst = None

            # Try to extract analyst name from args or kwargs
            for arg in args:
                if hasattr(arg, 'agent_key'):
                    analyst = arg.agent_key
                    break

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    # Check if this error is retryable
                    is_retryable = any(isinstance(e, err_type) for err_type in retryable_errors)

                    if not is_retryable or attempt == max_retries - 1:
                        # Not retryable or last attempt, re-raise
                        if analyst:
                            raise AnalystError(str(e), ErrorType.UNKNOWN, analyst) from e
                        raise

                    # Calculate backoff with jitter
                    wait_time = backoff_factor ** attempt
                    jitter_amount = wait_time * jitter
                    wait_time += jitter_amount

                    logger.warning(
                        f"[{analyst or 'API'}] Call failed (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {wait_time:.1f}s: {e}"
                    )
                    time.sleep(wait_time)

            # Should not reach here
            if last_exception:
                if analyst:
                    raise AnalystError(f"Max retries exceeded: {last_exception}",
                                     ErrorType.UNKNOWN, analyst) from last_exception
                raise last_exception
            raise RuntimeError("Unexpected error in retry logic")

        return wrapper
    return decorator


def handle_analyst_errors(func: Callable) -> Callable:
    """
    Decorator to handle analyst errors and return neutral signals.

    This decorator catches all exceptions from analyst functions
    and returns a neutral signal with error information.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        analyst = None

        # Try to extract analyst name
        for arg in args:
            if hasattr(arg, 'agent_key'):
                analyst = arg.agent_key
                break
            elif hasattr(arg, '__class__') and hasattr(arg.__class__, '__name__'):
                # Try to get class name
                analyst = arg.__class__.__name__

        try:
            return func(*args, **kwargs)
        except AnalystError as e:
            # Already classified error
            logger.error(f"[{e.analyst or analyst}] Analyst error: {e}")
            ErrorStats.record_error(e.analyst or analyst, e.error_type.value, str(e))
            return create_neutral_signal(str(e), e.analyst or analyst)
        except Exception as e:
            # Unclassified error
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"[{analyst}] {error_msg}")
            ErrorStats.record_error(analyst, ErrorType.UNKNOWN.value, str(e))
            return create_neutral_signal(error_msg, analyst)

    return wrapper


class ErrorStats:
    """Error statistics and monitoring."""

    _instance = None
    errors_by_analyst = defaultdict(list)
    error_counts = defaultdict(int)
    total_errors = 0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def record_error(cls, analyst: str, error_type: str, error_message: str):
        """Record an error for monitoring."""
        cls.total_errors += 1
        cls.error_counts[error_type] += 1

        cls.errors_by_analyst[analyst].append({
            "type": error_type,
            "message": error_message,
            "timestamp": datetime.now().isoformat()
        })

        # Keep only last 100 errors per analyst to avoid memory growth
        if len(cls.errors_by_analyst[analyst]) > 100:
            cls.errors_by_analyst[analyst] = cls.errors_by_analyst[analyst][-100:]

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """Get error statistics."""
        return {
            "total_errors": cls.total_errors,
            "error_counts": dict(cls.error_counts),
            "analysts_with_errors": len(cls.errors_by_analyst),
            "recent_errors": {
                analyst: errors[-10:]  # Last 10 errors per analyst
                for analyst, errors in cls.errors_by_analyst.items()
            }
        }

    @classmethod
    def clear(cls):
        """Clear error statistics (for testing)."""
        cls.errors_by_analyst.clear()
        cls.error_counts.clear()
        cls.total_errors = 0


# Default error handler for all analysts
default_error_handler = handle_analyst_errors