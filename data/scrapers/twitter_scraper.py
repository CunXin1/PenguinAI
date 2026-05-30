"""
Twitter/X scraper using Playwright (browser automation).
Targets a curated list of finance influencer accounts.
No official API required — respects rate limits via sleep intervals.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Curated VIP finance accounts to track
VIP_ACCOUNTS = [
    "jimcramer",       # Jim Cramer (contrarian indicator)
    "elonmusk",        # Market mover
    "CathieDWood",     # ARK Invest
    "chamath",         # Chamath Palihapitiya
    "natesilver538",   # analyst
    # Add more as needed
]

TICKER_PATTERN = re.compile(r'\$([A-Z]{1,5})')   # cashtag format: $NVDA


class TwitterScraper:
    def __init__(self):
        self._browser = None

    async def fetch_new_posts(self, tweets_per_account: int = 10) -> list[dict]:
        """
        Scrape recent tweets from VIP accounts.
        Returns list of post dicts compatible with social_posts schema.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
            return []

        posts = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()

            for account in VIP_ACCOUNTS:
                try:
                    account_posts = await self._scrape_account(page, account, tweets_per_account)
                    posts.extend(account_posts)
                    await asyncio.sleep(2)  # polite delay between accounts
                except Exception as e:
                    logger.error("Failed to scrape @%s: %s", account, e)

            await browser.close()

        return posts

    async def _scrape_account(self, page, account: str, limit: int) -> list[dict]:
        await page.goto(f"https://x.com/{account}", wait_until="networkidle", timeout=15000)
        await page.wait_for_selector('[data-testid="tweet"]', timeout=10000)

        tweets = await page.query_selector_all('[data-testid="tweet"]')
        posts = []

        for tweet in tweets[:limit]:
            try:
                text_el = await tweet.query_selector('[data-testid="tweetText"]')
                if not text_el:
                    continue
                content = await text_el.inner_text()
                tickers = TICKER_PATTERN.findall(content)

                for ticker in tickers or [None]:
                    posts.append({
                        "time": datetime.now(timezone.utc),   # precise timestamp requires API
                        "ticker": ticker,
                        "platform": "twitter",
                        "author": account,
                        "content": content[:1000],
                        "url": f"https://x.com/{account}",
                        "is_vip": True,
                    })
            except Exception as e:
                logger.debug("Tweet parse error for @%s: %s", account, e)

        return posts
