"""
Test configuration and fixtures for QuantArena tests.
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime
import sys
import types
import importlib.util
from pathlib import Path


class _DummyChatModel:
    """Minimal stand-in for optional langchain chat model classes in tests."""

    def __init__(self, *args, **kwargs):
        pass


def _ensure_module(name: str, attrs: dict):
    """Register a lightweight module stub if dependency is unavailable."""
    if name in sys.modules:
        return
    if importlib.util.find_spec(name) is not None:
        return
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


# Optional LLM provider deps are not required for unit tests in this repository.
_ensure_module("langchain_openai", {"ChatOpenAI": _DummyChatModel})
_ensure_module("langchain_anthropic", {"ChatAnthropic": _DummyChatModel})
_ensure_module("langchain_deepseek", {"ChatDeepSeek": _DummyChatModel})
_ensure_module("langchain_ollama", {"ChatOllama": _DummyChatModel})
_ensure_module("yfinance", {})
_ensure_module("supabase", {"create_client": lambda *args, **kwargs: None})

if (
    "langchain_core" not in sys.modules
    and importlib.util.find_spec("langchain_core") is None
):
    langchain_core = types.ModuleType("langchain_core")
    language_models = types.ModuleType("langchain_core.language_models")
    chat_models = types.ModuleType("langchain_core.language_models.chat_models")
    chat_models.BaseChatModel = _DummyChatModel
    language_models.chat_models = chat_models
    langchain_core.language_models = language_models
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.language_models"] = language_models
    sys.modules["langchain_core.language_models.chat_models"] = chat_models

# Setup project paths using unified path manager
from shared.utils.path_manager import setup_paths
setup_paths()


# Env vars that change provider routing or credentials. Modules under test
# call load_dotenv() at import time, so a developer's .env (or shell) leaks
# into os.environ and silently flips routing-dependent assertions. Scrub them
# before every test; tests that need one set it explicitly via monkeypatch.
_AMBIENT_ENV_VARS = [
    "DEEPFUND_US_API_SOURCE",
    "COMPANY_NEWS_PROVIDER",
    "COMPANY_NEWS_REPLAY_PATH",
    "FMP_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "TAVILY_API_KEY",
    "TUSHARE_API_KEY",
    "SEC_EDGAR_USER_AGENT",
]


@pytest.fixture(autouse=True)
def _isolate_ambient_env(monkeypatch):
    """Keep ambient .env / shell state from leaking into test assertions."""
    for var in _AMBIENT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def mock_db():
    """Create a mock database instance."""
    db = Mock()
    db.save_signal = Mock()
    db.save_decision = Mock()
    db.get_decision_memory = Mock(return_value=[])
    return db


@pytest.fixture
def mock_router():
    """Create a mock API router."""
    router = Mock()
    router.get_cn_stock_daily_candles_df = Mock(return_value=None)
    router.get_cn_stock_fundamentals = Mock(return_value=None)
    router.get_cn_stock_last_close_price = Mock(return_value=100.0)
    return router


@pytest.fixture
def mock_llm_config():
    """Create a mock LLM configuration."""
    return {
        "provider": "test",
        "model": "test-model",
        "api_key": "test-key"
    }


@pytest.fixture
def sample_portfolio():
    """Create a sample portfolio for testing."""
    from deepfund.src.graph.schema import Portfolio, Position

    return Portfolio(
        id="test-portfolio-id",
        cashflow=100000.0,
        positions={
            "AAPL": Position(ticker="AAPL", shares=10, value=1500.0)
        }
    )


@pytest.fixture
def sample_analyst_signals():
    """Create sample analyst signals for testing."""
    from deepfund.src.graph.schema import AnalystSignal
    from deepfund.src.graph.constants import Signal

    return [
        AnalystSignal(signal=Signal.BULLISH, justification="Strong fundamentals"),
        AnalystSignal(signal=Signal.NEUTRAL, justification="Mixed technicals")
    ]


@pytest.fixture
def sample_fund_state(sample_portfolio, sample_analyst_signals, mock_llm_config):
    """Create a sample FundState for testing."""
    from deepfund.src.graph.schema import FundState

    return FundState(
        ticker="AAPL",
        trading_date="2024-01-15",
        exp_name="test-experiment",
        portfolio=sample_portfolio,
        analyst_signals=sample_analyst_signals,
        llm_config=mock_llm_config,
        personality="balanced",
        num_tickers=1
    )


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database path for testing."""
    return str(tmp_path / "test_deepfund.db")


@pytest.fixture
def clean_error_stats():
    """Clean error stats before and after each test."""
    from deepfund.src.util.error_handler import ErrorStats

    ErrorStats.clear()
    yield
    ErrorStats.clear()
