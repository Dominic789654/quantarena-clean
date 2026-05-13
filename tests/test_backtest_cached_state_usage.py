from datetime import datetime
from unittest.mock import Mock, patch

import pandas as pd

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

from agents.portfolio_manager import portfolio_agent
from agents.analysts.technical import TechnicalAnalyst
from graph.constants import Action, Signal
from graph.schema import AnalystSignal, Decision, FundState, Portfolio, PositionRisk


def _portfolio() -> Portfolio:
    return Portfolio(id="p1", cashflow=100000.0, positions={})


def test_portfolio_manager_prefers_cached_current_price():
    state = FundState(
        ticker="AAPL",
        exp_name="exp",
        trading_date=datetime(2026, 2, 23),
        market="us",
        api_source={"default": "alpha_vantage", "us_source": "alpha_vantage"},
        llm_config={"provider": "test", "model": "test-model"},
        portfolio=_portfolio(),
        num_tickers=2,
        personality="balanced",
        analyst_signals=[AnalystSignal(signal=Signal.BULLISH, justification="ok")],
        decision=None,
        current_price=123.45,
        db_path="data/signal_flux.db",
        is_backtest=True,
    )

    mock_db = Mock()
    mock_db.get_decision_memory.return_value = []

    with patch("agents.portfolio_manager.get_db", return_value=mock_db), \
         patch("agents.portfolio_manager.Router") as mock_router_cls, \
         patch("agents.portfolio_manager.agent_call") as mock_agent_call:
        mock_agent_call.side_effect = [
            PositionRisk(optimal_position_ratio=0.1, justification="ok"),
            Decision(action=Action.HOLD, shares=0, price=0.0, justification="hold"),
        ]

        result = portfolio_agent(state)

    mock_router_cls.assert_not_called()
    assert result["decision"].price == 123.45


def test_technical_analyst_loads_backtest_prices_from_db(tmp_path):
    from deepear.src.utils.database_manager import DatabaseManager

    db_path = tmp_path / "prices.db"
    db = DatabaseManager(str(db_path))
    try:
        df = pd.DataFrame(
            {
                "date": ["2026-02-20", "2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26", "2026-02-27"],
                "open": [100, 101, 102, 103, 104, 105],
                "close": [101, 102, 103, 104, 105, 106],
                "high": [102, 103, 104, 105, 106, 107],
                "low": [99, 100, 101, 102, 103, 104],
                "volume": [1000, 1001, 1002, 1003, 1004, 1005],
                "change_pct": [0, 0.99, 0.98, 0.97, 0.96, 0.95],
            }
        )
        db.save_stock_prices("AAPL", df)
    finally:
        db.close()

    state = FundState(
        ticker="AAPL",
        exp_name="exp",
        trading_date=datetime(2026, 2, 27),
        market="us",
        api_source={"default": "alpha_vantage", "us_source": "alpha_vantage"},
        llm_config={"provider": "test", "model": "test-model"},
        portfolio=_portfolio(),
        num_tickers=1,
        personality="balanced",
        analyst_signals=[],
        decision=None,
        current_price=106.0,
        db_path=str(db_path),
        is_backtest=True,
    )

    analyst = TechnicalAnalyst()
    router = Mock()
    router.get_us_stock_daily_candles_df.side_effect = AssertionError("should use cached DB prices")

    data = analyst.fetch_data(state, router)

    assert data["ticker"] == "AAPL"
    assert set(data["signal_results"].keys()) == {
        "trend",
        "mean_reversion",
        "rsi",
        "volatility",
        "volume",
        "price_levels",
    }
