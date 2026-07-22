"""Unit tests for the social sentiment analyst (Reddit/ApeWisdom-backed)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

# Ensure deepfund's `agents` package wins over deepear's on sys.path.
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

from deepfund.src.agents.analysts.social_sentiment import SocialSentimentAnalyst  # noqa: E402
from deepfund.src.agents.registry import AgentRegistry  # noqa: E402
from deepfund.src.apis.apewisdom.api_model import SocialMention  # noqa: E402
from deepfund.src.graph.constants import AgentKey  # noqa: E402


MU = SocialMention(
    rank=1, ticker="MU", name="Micron Technology",
    mentions=474, upvotes=2441, rank_24h_ago=2, mentions_24h_ago=237,
)
SPY = SocialMention(rank=2, ticker="SPY", name="SPDR S&P 500", mentions=262)


def _make_state(ticker="MU", market="us"):
    return {"ticker": ticker, "trading_date": "2026-07-22", "market": market}


def _make_router(mention=MU, trending=(MU, SPY)):
    router = Mock()
    router.get_us_social_ticker_mentions.return_value = mention
    router.get_us_social_trending.return_value = list(trending)
    return router


def test_agent_key_registered():
    assert AgentKey.SOCIAL_SENTIMENT == "social_sentiment"
    assert AgentKey.SOCIAL_SENTIMENT in AgentRegistry.get_all_analyst_keys()

    AgentRegistry.run_registry()
    assert AgentRegistry.get_agent_func_by_key(AgentKey.SOCIAL_SENTIMENT) is not None
    assert AgentRegistry.check_agent_key(AgentKey.SOCIAL_SENTIMENT)


def test_thresholds_loaded_from_config():
    analyst = SocialSentimentAnalyst()
    assert analyst.thresholds.get("filter_key") == "wallstreetbets"
    assert int(analyst.thresholds.get("trending_top_n")) == 10


def test_fetch_data_returns_stats_and_trending():
    analyst = SocialSentimentAnalyst()
    router = _make_router()

    data = analyst.fetch_data(_make_state(), router)

    router.get_us_social_ticker_mentions.assert_called_once_with(
        "MU", filter_key="wallstreetbets"
    )
    router.get_us_social_trending.assert_called_once_with(
        filter_key="wallstreetbets", limit=10
    )
    assert '"ticker":"MU"' in data["ticker_stats"].replace(" ", "")
    assert "1. MU: 474 mentions (+237 vs 24h ago)" in data["trending"]
    # Trending entry without 24h history omits the delta clause.
    assert "2. SPY: 262 mentions" in data["trending"]
    assert "vs 24h ago)" not in data["trending"].splitlines()[1]


def test_fetch_data_unranked_ticker_reports_low_attention():
    analyst = SocialSentimentAnalyst()
    router = _make_router(mention=None)

    data = analyst.fetch_data(_make_state(ticker="ZZZZ"), router)

    assert "not currently ranked" in data["ticker_stats"]
    assert "low retail attention" in data["ticker_stats"]


def test_fetch_data_rejects_cn_market():
    analyst = SocialSentimentAnalyst()

    with pytest.raises(ValueError, match="US market only"):
        analyst.fetch_data(_make_state(market="cn"), _make_router())


def test_build_prompt_includes_data_and_output_format():
    analyst = SocialSentimentAnalyst()
    prompt = analyst.build_prompt({
        "ticker_stats": "MU-STATS-MARKER",
        "trending": "TRENDING-MARKER",
    })

    assert "MU-STATS-MARKER" in prompt
    assert "TRENDING-MARKER" in prompt
    assert "signal" in prompt  # ANALYST_OUTPUT_FORMAT appended


def test_behavioral_momentum_config_includes_social_sentiment():
    import yaml
    from pathlib import Path

    config_path = (
        Path(__file__).parent.parent
        / "deepfund" / "src" / "config" / "behavioral_momentum.yaml"
    )
    config = yaml.safe_load(config_path.read_text())

    assert "social_sentiment" in config["workflow_analysts"]
