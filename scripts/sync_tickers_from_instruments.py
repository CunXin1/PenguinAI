"""
Sync the app-facing ``tickers`` universe from the data-layer ``instruments``
dimension (the real 30-min data coverage — one row per symbol with bars in
``bars_30m``).

The signal universe-gate, watchlist add, and screener all key off ``tickers``;
``instruments`` is auto-populated by the 30-min data import. Without this sync
``tickers`` only holds the tiny hand-curated bootstrap set, so every other
symbol you actually have data for shows up as "not in universe".

Run after importing/refreshing 30-min data:
    python scripts/sync_tickers_from_instruments.py

Idempotent. Existing ``tickers`` rows (e.g. the curated bootstrap entries with
real names/sectors) are preserved — ``name`` is only filled in where it's still
a placeholder. New symbols get ``name = symbol`` (placeholder) + ``tags =
[asset_type]``; enrich names/sectors later (e.g. via Massive reference).
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def sync():
    from backend.app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        before = (await db.execute(text("SELECT count(*) FROM tickers"))).scalar_one()

        # Insert every instrument symbol not already present. Placeholder name =
        # symbol; tags carry the asset_type (stock|etf). DISTINCT ON guards the
        # rare symbol-as-both-stock-and-etf case (tickers PK is ticker alone).
        result = await db.execute(
            text("""
                INSERT INTO tickers (ticker, name, tags, is_active)
                SELECT DISTINCT ON (symbol)
                       symbol, symbol, ARRAY[asset_type], true
                FROM instruments
                ORDER BY symbol, asset_type
                ON CONFLICT (ticker) DO NOTHING
            """)
        )
        await db.commit()
        after = (await db.execute(text("SELECT count(*) FROM tickers"))).scalar_one()

    logger.info(
        "tickers universe: %d → %d (%d inserted from instruments)",
        before,
        after,
        result.rowcount,
    )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(sync())
