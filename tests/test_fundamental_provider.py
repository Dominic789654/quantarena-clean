import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

from backtest.providers import ReplayFundamentalsProvider
from deepfund.src.agents.analysts.fundamental import FundamentalAnalyst


class _FundamentalsPayload:
    def __init__(self, text: str = '{"pe_ratio": "12.5"}'):
        self.text = text

    def model_dump_json(self):
        return self.text


def test_fundamental_analyst_uses_injected_fundamentals_provider():
    payload = {"pe_ratio": "12.5"}
    provider = ReplayFundamentalsProvider({"AAPL": payload})
    router = Mock()
    state = {"ticker": "AAPL", "market": "us"}

    data = FundamentalAnalyst(fundamentals_provider=provider).fetch_data(state, router)

    assert data.model_dump_json() == '{"pe_ratio": "12.5"}'
    router.get_us_stock_fundamentals.assert_not_called()
    router.get_cn_stock_fundamentals.assert_not_called()


@pytest.mark.parametrize(
    ("market", "expected_method", "unexpected_method"),
    [
        ("us", "get_us_stock_fundamentals", "get_cn_stock_fundamentals"),
        ("cn", "get_cn_stock_fundamentals", "get_us_stock_fundamentals"),
    ],
)
def test_fundamental_analyst_default_path_uses_router(
    market,
    expected_method,
    unexpected_method,
):
    payload = _FundamentalsPayload()
    router = Mock()
    getattr(router, expected_method).return_value = payload
    state = {"ticker": "AAPL", "market": market}

    data = FundamentalAnalyst().fetch_data(state, router)

    assert data is payload
    getattr(router, expected_method).assert_called_once_with(ticker="AAPL")
    getattr(router, unexpected_method).assert_not_called()


def test_fundamental_analyst_build_prompt_accepts_replay_payload():
    payload = _FundamentalsPayload('{"pe_ratio": "12.5", "return_on_equity_ttm": "0.21"}')

    prompt = FundamentalAnalyst().build_prompt(payload)

    assert '"pe_ratio": "12.5"' in prompt
    assert '"return_on_equity_ttm": "0.21"' in prompt
