import logging

logger = logging.getLogger(__name__)


class TwitterScraper:
    async def fetch_new_posts(self) -> list[dict]:
        logger.info("TwitterScraper stub — no posts fetched")
        return []
