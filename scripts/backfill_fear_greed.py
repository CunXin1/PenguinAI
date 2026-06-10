#!/usr/bin/env python3
"""Backfill fear_greed_index with a VIX-derived history (multi-year).

CNN's public Fear & Greed endpoint only serves ~1 year of history, so the
dashboard's longer ranges (e.g. 5Y) would otherwise flat-line at one year. This
script reconstructs older daily Fear & Greed readings from the VIX history
already in ``volatility_index`` (decades available) using the SAME inverted
252-day percentile model the live loader falls back to
(``data.fear_greed.fallback.compute_fng_from_vix``) — so the methodology matches
the app's own ``source='computed'`` readings.

Existing data is preserved: ``ON CONFLICT (time) DO NOTHING`` keeps the real CNN
rows for the most recent year untouched; only older, missing days are filled.
Backfilled rows are tagged ``source='computed'``.

RUN (from repo root, with .env present and Postgres reachable on localhost):
    python3 scripts/backfill_fear_greed.py              # 5 years (default)
    python3 scripts/backfill_fear_greed.py --years 5
    python3 scripts/backfill_fear_greed.py --dry-run    # compute + preview, no writes
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Reuse the project's canonical VIX→Fear&Greed model (the live loader's fallback)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.fear_greed.fallback import compute_fng_from_vix  # noqa: E402

logger = logging.getLogger("backfill_fng")

_UPSERT = text(
    """
    INSERT INTO fear_greed_index (time, score, rating, components, source)
    VALUES (:time, :score, :rating, NULL, 'computed')
    ON CONFLICT (time) DO NOTHING
    """
)


def _day(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


async def backfill(db_url: str, years: int, *, dry_run: bool = False) -> None:
    engine = create_async_engine(db_url)
    try:
        # Read the FULL VIX history so every day in the output range gets a
        # complete 252-day trailing percentile window (no edge truncation).
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT time, close FROM volatility_index "
                    "WHERE symbol = 'VIX' AND close IS NOT NULL ORDER BY time ASC"
                )
            )
            vix_rows = [{"time": r.time, "close": float(r.close)} for r in res]

        if not vix_rows:
            logger.error("no VIX rows in volatility_index — nothing to compute")
            return
        logger.info(
            "loaded %d VIX rows (%s → %s)",
            len(vix_rows), vix_rows[0]["time"].date(), vix_rows[-1]["time"].date(),
        )

        payload = compute_fng_from_vix(vix_rows)
        if not payload:
            logger.error("compute_fng_from_vix returned None (too little VIX data)")
            return

        # Keep a small margin beyond the requested window so the chart's left
        # edge is fully populated at exactly N years.
        cutoff = _day(datetime.now(UTC) - timedelta(days=365 * years + 30))
        rows = [
            {"time": _day(d), "score": round(score, 2), "rating": rating}
            for d, score, rating in payload["history"]
            if _day(d) >= cutoff
        ]
        logger.info(
            "computed %d daily F&G rows since %s (~%d years)",
            len(rows), cutoff.date(), years,
        )

        if dry_run:
            preview = rows[:3] + (["..."] if len(rows) > 6 else []) + rows[-3:]
            for r in preview:
                if r == "...":
                    logger.info("  ...")
                else:
                    logger.info("  %s  score=%6.2f  %s", r["time"].date(), r["score"], r["rating"])
            logger.info("DRY RUN — no writes")
            return

        async with engine.begin() as conn:
            before = (
                await conn.execute(text("SELECT count(*) FROM fear_greed_index"))
            ).scalar_one()
            await conn.execute(_UPSERT, rows)
            after = (
                await conn.execute(text("SELECT count(*) FROM fear_greed_index"))
            ).scalar_one()

        inserted = after - before
        logger.info(
            "DONE — %d new rows inserted, %d existing preserved (CNN untouched); table now %d rows",
            inserted, len(rows) - inserted, after,
        )
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser(description="Backfill fear_greed_index from VIX history.")
    p.add_argument("--years", type=int, default=5, help="Years of history to fill (default 5).")
    p.add_argument("--dry-run", action="store_true", help="Compute + preview only, no DB writes.")
    args = p.parse_args()

    # Load .env (same lightweight pattern as scripts/backfill_1min_massive.py)
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    db_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
    )
    # Running on the host: the DB is on localhost, not the compose service name.
    db_url = db_url.replace("@timescaledb:", "@localhost:")
    if "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    asyncio.run(backfill(db_url, args.years, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
