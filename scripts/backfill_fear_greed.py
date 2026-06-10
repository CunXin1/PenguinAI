#!/usr/bin/env python3
"""Backfill fear_greed_index with the full REAL CNN history.

CNN's graphdata endpoint returns only ~1 year from the bare URL, but several
years when a start date is in the path — data exists from ~2020-09-01 onward.
This pulls that full history and upserts it through the live loader's DO-UPDATE
path, so real CNN readings replace any earlier estimates (e.g. VIX-proxy rows).
Rows are tagged source='cnn'.

RUN (from repo root, with .env present and Postgres reachable on localhost):
    python3 scripts/backfill_fear_greed.py                       # from 2020-09-01
    python3 scripts/backfill_fear_greed.py --start-date 2021-01-01
    python3 scripts/backfill_fear_greed.py --dry-run             # fetch + preview, no writes
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.fear_greed.cnn import fetch_fear_greed  # noqa: E402
from data.fear_greed.loader import backfill_fng_from_cnn  # noqa: E402

logger = logging.getLogger("backfill_fng")


async def _dry_run(start_date: str) -> None:
    fng = await fetch_fear_greed(start_date=start_date)
    if not fng:
        logger.error("CNN returned no data for start=%s (data begins ~2020-09-01)", start_date)
        return
    hist = fng["history"]
    logger.info(
        "CNN returned %d daily points (%s → %s); current=%.1f %s",
        len(hist), hist[0][0].date(), hist[-1][0].date(), fng["score"], fng["rating"],
    )
    for d, s, r in hist[:3] + hist[-3:]:
        logger.info("  %s  score=%6.2f  %s", d.date(), s, r)
    logger.info("DRY RUN — no writes")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser(description="Backfill fear_greed_index from CNN's full history.")
    p.add_argument(
        "--start-date", default="2020-09-01",
        help="Earliest day (YYYY-MM-DD). CNN data begins ~2020-09-01; earlier returns HTTP 500.",
    )
    p.add_argument("--dry-run", action="store_true", help="Fetch + preview only, no DB writes.")
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

    if args.dry_run:
        asyncio.run(_dry_run(args.start_date))
    else:
        n = asyncio.run(backfill_fng_from_cnn(db_url, args.start_date))
        logger.info("DONE — %d rows upserted from CNN since %s", n, args.start_date)


if __name__ == "__main__":
    main()
