"""FOMC statement loader — scrape, score, and upsert into ``fomc_statements``.

Orchestrates the full pipeline:
  1. Discover statement URLs from the Federal Reserve website
  2. Filter to statements not already in the DB (incremental by default)
  3. Download each statement's full text
  4. Score hawk/dove via FinBERT (``data.fomc.scorer``)
  5. Upsert into ``fomc_statements`` (TimescaleDB hypertable)

RUN (from repo root, with .env present and Postgres up):
    python -m data.fomc.loader
    python -m data.fomc.loader --start-year 2020
    python -m data.fomc.loader --full            # re-score everything
    make fetch-fomc
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from data.fomc.scraper import FomcStatementMeta, discover_statement_urls, fetch_statement_text
from data.fomc.scorer import score_statement

logger = logging.getLogger("fomc_loader")

_UPSERT_SQL = text("""
    INSERT INTO fomc_statements (time, document_url, hawk_dove_score, summary, raw_text)
    VALUES (:time, :document_url, :hawk_dove_score, :summary, :raw_text)
    ON CONFLICT (time) DO UPDATE SET
        hawk_dove_score = EXCLUDED.hawk_dove_score,
        summary         = EXCLUDED.summary,
        raw_text        = EXCLUDED.raw_text,
        document_url    = EXCLUDED.document_url
""")

_EXISTING_DATES_SQL = text(
    "SELECT DISTINCT time::date::text FROM fomc_statements"
)

THROTTLE_SECONDS = 0.5


class LoaderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"


async def _get_existing_dates(engine) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(_EXISTING_DATES_SQL)
        return {str(r[0]) for r in rows}


async def run_loader(
    database_url: str,
    *,
    start_year: int = 2000,
    end_year: int | None = None,
    full: bool = False,
    score: bool = True,
) -> int:
    """Run the full FOMC pipeline. Returns the number of rows upserted."""
    engine = create_async_engine(database_url)

    try:
        existing = set() if full else await _get_existing_dates(engine)
        if existing:
            logger.info("found %d existing statements in DB", len(existing))

        today_str = datetime.now(UTC).strftime("%Y-%m-%d")

        headers = {"User-Agent": "PenguinAI/0.1 (FOMC research)"}
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=headers,
        ) as client:
            all_metas = await discover_statement_urls(
                client, start_year=start_year, end_year=end_year,
            )

            to_fetch: list[FomcStatementMeta] = [
                m for m in all_metas
                if m.date not in existing and m.date <= today_str
            ]

            if not to_fetch:
                logger.info("all %d statements already in DB — nothing to do", len(all_metas))
                return 0

            logger.info(
                "%d new statements to fetch (of %d discovered)",
                len(to_fetch), len(all_metas),
            )

            rows: list[dict] = []
            for i, meta in enumerate(to_fetch):
                logger.info(
                    "[%d/%d] fetching %s …",
                    i + 1, len(to_fetch), meta.date,
                )
                raw_text = await fetch_statement_text(client, meta.url)
                if not raw_text:
                    logger.warning("  empty statement for %s — skipping", meta.date)
                    continue

                hawk_dove_score = None
                summary = None
                if score:
                    try:
                        result = score_statement(raw_text)
                        hawk_dove_score = result.hawk_dove_score
                        summary = result.summary
                        logger.info(
                            "  scored %s: %+.4f (%s)",
                            meta.date, hawk_dove_score, summary,
                        )
                    except Exception as exc:
                        logger.warning("  scoring failed for %s: %s", meta.date, exc)

                stmt_time = datetime.strptime(meta.date, "%Y-%m-%d").replace(
                    hour=14, tzinfo=UTC,
                )

                rows.append({
                    "time": stmt_time,
                    "document_url": meta.url,
                    "hawk_dove_score": hawk_dove_score,
                    "summary": summary,
                    "raw_text": raw_text,
                })

                await asyncio.sleep(THROTTLE_SECONDS)

        if not rows:
            logger.info("no rows to upsert")
            return 0

        async with engine.begin() as conn:
            await conn.execute(_UPSERT_SQL, rows)

        logger.info("upserted %d FOMC statements", len(rows))
        return len(rows)

    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="FOMC statement loader")
    parser.add_argument(
        "--start-year", type=int, default=2000,
        help="Earliest year to fetch (default: 2000)",
    )
    parser.add_argument(
        "--end-year", type=int, default=None,
        help="Latest year to fetch (default: current year)",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Re-fetch and re-score all statements (ignore existing DB rows)",
    )
    parser.add_argument(
        "--no-score", action="store_true",
        help="Skip FinBERT scoring (store raw text only, score later)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-16s  %(levelname)-5s  %(message)s",
        datefmt="%H:%M:%S",
    )

    settings = LoaderSettings()
    count = asyncio.run(run_loader(
        database_url=settings.DATABASE_URL,
        start_year=args.start_year,
        end_year=args.end_year,
        full=args.full,
        score=not args.no_score,
    ))
    print(f"\nDone — {count} statements upserted.")


if __name__ == "__main__":
    main()
