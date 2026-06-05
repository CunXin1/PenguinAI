from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_ticker_sentiment(
    ticker: str,
    db: AsyncSession,
    hours: int = 72,
) -> tuple[float | None, int]:
    """
    Aggregate FinBERT scores from social_posts for a ticker over the past N hours.
    Returns (mean_score, post_count). Score is None if no posts found.
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    row = await db.execute(
        text("""
            SELECT
                AVG(finbert_score) AS mean_score,
                COUNT(*)           AS post_count
            FROM social_posts
            WHERE (ticker = :ticker OR ticker IS NULL)
              AND time >= :since
              AND finbert_score IS NOT NULL
        """),
        {"ticker": ticker, "since": since},
    )
    result = row.mappings().one()
    score = float(result["mean_score"]) if result["mean_score"] is not None else None
    count = int(result["post_count"])
    return score, count
