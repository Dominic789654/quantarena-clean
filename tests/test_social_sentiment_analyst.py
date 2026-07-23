"""Unit tests for the social sentiment analyst (Reddit/ApeWisdom-backed)."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

# `agents` package resolution is pinned centrally by setup_paths() /
# the session fixture in conftest.py — no per-file sys.path hack needed.
from deepfund.src.agents.analysts.social_sentiment import SocialSentimentAnalyst
from deepfund.src.agents.registry import AgentRegistry
from deepfund.src.apis.apewisdom.api_model import SocialMention
from deepfund.src.graph.constants import AgentKey


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

    router.get_us_social_ticker_mentions.assert_called_once()
    mention_kwargs = router.get_us_social_ticker_mentions.call_args
    assert mention_kwargs.args == ("MU",)
    assert mention_kwargs.kwargs["filter_key"] == "wallstreetbets"
    assert mention_kwargs.kwargs["as_of"] is not None  # trading_date threaded through

    router.get_us_social_trending.assert_called_once()
    trending_kwargs = router.get_us_social_trending.call_args.kwargs
    assert trending_kwargs["filter_key"] == "wallstreetbets"
    assert trending_kwargs["limit"] == 10
    assert trending_kwargs["as_of"] is not None
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


from unittest.mock import patch  # noqa: E402


@patch("deepfund.src.agents.analysts.base.get_db")
@patch("deepfund.src.agents.analysts.base.agent_call")
@patch("deepfund.src.agents.analysts.base.Router")
def test_analyze_end_to_end(mock_router_cls, mock_agent_call, mock_get_db):
    """Pin the full wiring: thresholds -> router fetch -> prompt -> signal."""
    from deepfund.src.graph.schema import AnalystSignal, Portfolio
    from deepfund.src.graph.constants import Signal

    mock_get_db.return_value = Mock()
    mock_router_cls.return_value = _make_router()
    mock_agent_call.return_value = AnalystSignal(
        signal=Signal.BULLISH, justification="strong retail momentum"
    )

    state = {
        "ticker": "MU",
        "trading_date": "2026-07-22",
        "market": "us",
        "exp_name": "test",
        "portfolio": Portfolio(id="p1", cashflow=1000.0, positions={}),
        "llm_config": {"provider": "test", "model": "test"},
        "skip_db_writes": True,
    }
    result = SocialSentimentAnalyst().analyze(state)

    assert result["analyst_signals"][0].signal == Signal.BULLISH
    call_kwargs = mock_agent_call.call_args.kwargs
    assert call_kwargs["agent_name"] == AgentKey.SOCIAL_SENTIMENT
    assert "474 mentions" in call_kwargs["prompt"]


def test_fetch_data_warns_on_historical_trading_date():
    """Historical backtests get current Reddit data — must be flagged, not silent."""
    from datetime import datetime

    analyst = SocialSentimentAnalyst()
    router = _make_router()

    with patch("deepfund.src.agents.analysts.social_sentiment.logger") as mock_logger:
        recent_state = _make_state()
        recent_state["trading_date"] = datetime.now().strftime("%Y-%m-%d")
        data = analyst.fetch_data(recent_state, router)
        assert not mock_logger.warning.called  # today's date: no lookahead

        old_state = _make_state()
        old_state["trading_date"] = "2025-01-06"
        analyst.fetch_data(old_state, router)
        assert mock_logger.warning.called

    assert data["ticker_stats"]  # the warning never blocks data


def test_lookahead_warning_suppressed_under_replay(monkeypatch):
    """local_only snapshot replay serves point-in-time data — no warning."""
    monkeypatch.setenv("APEWISDOM_SNAPSHOT_MODE", "local_only")
    analyst = SocialSentimentAnalyst()
    router = _make_router()

    old_state = _make_state()
    old_state["trading_date"] = "2025-01-06"
    with patch("deepfund.src.agents.analysts.social_sentiment.logger") as mock_logger:
        analyst.fetch_data(old_state, router)
        assert not mock_logger.warning.called


def test_behavioral_momentum_config_includes_social_sentiment():
    import yaml
    from pathlib import Path

    config_path = (
        Path(__file__).parent.parent
        / "deepfund" / "src" / "config" / "behavioral_momentum.yaml"
    )
    config = yaml.safe_load(config_path.read_text())

    assert "social_sentiment" in config["workflow_analysts"]
