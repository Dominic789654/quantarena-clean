"""
Social Sentiment Analyst - Reddit retail-attention signals

Analyzes Reddit mention statistics (ApeWisdom) to gauge retail crowd
attention and its 24-hour momentum for a ticker. US market only.
"""

from datetime import datetime, timedelta
from typing import Dict

from graph.schema import FundState
from graph.constants import AgentKey
from llm.prompt import SOCIAL_SENTIMENT_PROMPT
from apis.router import Router
from util.logger import logger
from .base import BaseAnalyst


class SocialSentimentAnalyst(BaseAnalyst):
    """
    Retail social-sentiment specialist based on Reddit mention rankings.
    High or rapidly rising mention counts flag crowd-attention momentum;
    extreme readings also carry contrarian risk.
    """

    def __init__(self):
        super().__init__(AgentKey.SOCIAL_SENTIMENT, SOCIAL_SENTIMENT_PROMPT)

    def fetch_data(self, state: FundState, router: Router) -> Dict[str, str]:
        """
        Fetch Reddit mention stats for the ticker plus the current
        trending list for market-attention context.

        ApeWisdom only covers US tickers, so CN-market runs fail fast and
        BaseAnalyst degrades the signal to Neutral.
        """
        ticker = state["ticker"]
        market = state.get("market", "us")
        if market == "cn":
            raise ValueError("social_sentiment analyst supports the US market only")

        # ApeWisdom has no historical API: signals always reflect *current*
        # Reddit attention. Flag historical runs so backtests can't silently
        # treat today's sentiment as point-in-time data.
        trading_date = state.get("trading_date")
        parsed_date = None
        if isinstance(trading_date, datetime):
            parsed_date = trading_date
        elif isinstance(trading_date, str):
            try:
                parsed_date = datetime.strptime(trading_date[:10], "%Y-%m-%d")
            except ValueError:
                parsed_date = None
        if parsed_date and datetime.now() - parsed_date > timedelta(days=2):
            logger.warning(
                f"[{self.agent_key}] trading_date {trading_date} is historical but "
                f"social sentiment reflects current Reddit data — lookahead in backtests"
            )

        filter_key = self.thresholds.get("filter_key", "wallstreetbets")
        top_n = int(self.thresholds.get("trending_top_n", 10))

        mention = router.get_us_social_ticker_mentions(ticker, filter_key=filter_key)
        if mention is None:
            ticker_stats = (
                f"{ticker} is not currently ranked in r/{filter_key} mentions "
                "(low retail attention)."
            )
        else:
            ticker_stats = mention.model_dump_json()

        trending = router.get_us_social_trending(filter_key=filter_key, limit=top_n)
        trending_lines = [
            f"{m.rank}. {m.ticker}: {m.mentions} mentions"
            + (f" ({m.mentions_change_24h:+d} vs 24h ago)" if m.mentions_change_24h is not None else "")
            for m in trending
        ]

        return {
            "ticker_stats": ticker_stats,
            "trending": "\n".join(trending_lines) or "No trending data available.",
        }

    def build_prompt(self, data: Dict[str, str]) -> str:
        return self.prompt_template.format(
            ticker_stats=data["ticker_stats"],
            trending=data["trending"],
        )


# Backward-compatible function interface
def social_sentiment_agent(state: FundState):
    """Social sentiment analysis agent function (backward compatible)."""
    return SocialSentimentAnalyst().analyze(state)
