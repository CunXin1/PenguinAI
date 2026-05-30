"""
Reddit scraper for r/wallstreetbets and other finance subreddits.
Uses PRAW. Extracts ticker mentions and post content.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import praw

from ml.core.config import ml_settings

logger = logging.getLogger(__name__)

SUBREDDITS = ["wallstreetbets", "stocks", "investing", "StockMarket"]
TICKER_PATTERN = re.compile(r'\b([A-Z]{1,5})\b')

# Common false positives to ignore
TICKER_BLACKLIST = {
    "I", "A", "THE", "AND", "OR", "TO", "OF", "IN", "IS", "IT", "BE",
    "AT", "BY", "AN", "ON", "IF", "UP", "DD", "CEO", "IPO", "ETF",
    "SEC", "Fed", "GDP", "CPI", "ATH", "YOLO", "IMO", "FOMO", "WSB",
}


class RedditScraper:
    def __init__(self):
        self._reddit = None

    def _ensure_connected(self):
        if self._reddit is None:
            self._reddit = praw.Reddit(
                client_id=ml_settings.REDDIT_CLIENT_ID,
                client_secret=ml_settings.REDDIT_CLIENT_SECRET,
                user_agent=ml_settings.REDDIT_USER_AGENT,
            )

    async def fetch_new_posts(self, limit_per_sub: int = 50) -> list[dict]:
        """Fetch recent hot posts from finance subreddits."""
        self._ensure_connected()
        posts = []
        for sub_name in SUBREDDITS:
            try:
                sub = self._reddit.subreddit(sub_name)
                for post in sub.new(limit=limit_per_sub):
                    tickers = self._extract_tickers(post.title + " " + (post.selftext or ""))
                    content = f"{post.title}\n{post.selftext[:500]}" if post.selftext else post.title
                    for ticker in tickers or [None]:
                        posts.append({
                            "time": datetime.fromtimestamp(post.created_utc, tz=timezone.utc),
                            "ticker": ticker,
                            "platform": "reddit",
                            "author": str(post.author),
                            "content": content[:1000],
                            "url": f"https://reddit.com{post.permalink}",
                            "is_vip": False,
                        })
            except Exception as e:
                logger.error("Reddit fetch failed for r/%s: %s", sub_name, e)
        return posts

    def _extract_tickers(self, text: str) -> list[str]:
        found = TICKER_PATTERN.findall(text)
        return list({t for t in found if t not in TICKER_BLACKLIST and len(t) >= 2})
