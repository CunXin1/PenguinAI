import logging

logger = logging.getLogger(__name__)


class RedditScraper:
    async def fetch_new_posts(self) -> list[dict]:
        logger.info("RedditScraper stub — no posts fetched")
        return []
