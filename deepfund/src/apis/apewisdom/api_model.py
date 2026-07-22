from typing import Optional
from pydantic import BaseModel


class SocialMention(BaseModel):
    """Retail social-sentiment mention stats for one ticker (ApeWisdom)."""
    rank: int
    ticker: str
    name: Optional[str] = None
    mentions: int = 0
    upvotes: int = 0
    rank_24h_ago: Optional[int] = None
    mentions_24h_ago: Optional[int] = None

    @property
    def mentions_change_24h(self) -> Optional[int]:
        if self.mentions_24h_ago is None:
            return None
        return self.mentions - self.mentions_24h_ago
