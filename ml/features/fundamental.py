from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_fundamentals(
    ticker: str,
    db: AsyncSession,
) -> tuple[float | None, float | None]:
    """
    Return (earnings_surprise_pct, pe_ratio) for ticker.
    Pulls most recent available rows from each table.
    """
    earnings_row = await db.execute(
        text("""
            SELECT eps_surprise_pct
            FROM earnings
            WHERE ticker = :ticker
            ORDER BY report_date DESC
            LIMIT 1
        """),
        {"ticker": ticker},
    )
    earnings_result = earnings_row.scalar_one_or_none()

    pe_row = await db.execute(
        text("""
            SELECT pe_ratio
            FROM fundamentals
            WHERE ticker = :ticker
            ORDER BY date DESC
            LIMIT 1
        """),
        {"ticker": ticker},
    )
    pe_result = pe_row.scalar_one_or_none()

    return (
        float(earnings_result) if earnings_result is not None else None,
        float(pe_result) if pe_result is not None else None,
    )
