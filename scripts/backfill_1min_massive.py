#!/usr/bin/env python3
"""Backfill market_data_1min from Massive API (1-year history, top symbols).

Fetches adjusted 1-minute bars and upserts directly into TimescaleDB.
Resumable: re-running skips symbols that already have >= 200 trading days of data.

RUN (from repo root, with .env present and Postgres up):
    python3 scripts/backfill_1min_massive.py
    python3 scripts/backfill_1min_massive.py --symbols AAPL SPY   # specific symbols
    python3 scripts/backfill_1min_massive.py --dry-run             # plan only
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg

logger = logging.getLogger("backfill_1min")

SYMBOLS = [
    # Mega-cap tech
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    # High-volume growth / meme
    "AMD", "PLTR", "COIN", "MSTR", "ARM", "NFLX",
    # Financials / Healthcare / Consumer
    "JPM", "V", "LLY", "COST",
    # ETFs
    "SPY", "QQQ", "IWM", "DIA", "VTI", "GLD", "SMH",
]

PAGE_LIMIT = 50_000
CONCURRENCY = 3
RATE_PER_SEC = 4.0


class _RateLimiter:
    def __init__(self, rate: float) -> None:
        self._interval = 1.0 / rate if rate > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self._next > now:
                await asyncio.sleep(self._next - now)
                now = loop.time()
            self._next = max(now, self._next) + self._interval


def _with_key(url: str, key: str) -> str:
    if not key or "apiKey=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}apiKey={key}"


async def _fetch_bars(
    client: httpx.AsyncClient, limiter: _RateLimiter,
    base: str, key: str, ticker: str, date_from: str, date_to: str,
) -> list[tuple]:
    """Fetch all adjusted 1-min bars for ticker over [from, to]."""
    url: str | None = _with_key(
        f"{base}/v2/aggs/ticker/{ticker}/range/1/minute/{date_from}/{date_to}"
        f"?adjusted=true&sort=asc&limit={PAGE_LIMIT}",
        key,
    )
    rows: list[tuple] = []
    pages = 0
    while url:
        await limiter.wait()
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("%s: transport error %r — stopping pagination", ticker, exc)
            break
        if resp.status_code == 429 or resp.status_code >= 500:
            delay = float(resp.headers.get("Retry-After", "5"))
            logger.warning("%s: HTTP %d — backing off %.1fs", ticker, resp.status_code, delay)
            await asyncio.sleep(delay)
            continue
        resp.raise_for_status()
        data = resp.json()
        for r in data.get("results") or []:
            t = r.get("t")
            o, h, lo, c = r.get("o"), r.get("h"), r.get("l"), r.get("c")
            if t is None or None in (o, h, lo, c):
                continue
            ts = datetime.fromtimestamp(t / 1000.0, tz=UTC)
            rows.append((
                ts, ticker,
                round(o, 4), round(h, 4), round(lo, 4), round(c, 4),
                int(round(float(r.get("v") or 0))),
                round(r["vw"], 4) if r.get("vw") else None,
            ))
        pages += 1
        nxt = data.get("next_url")
        url = _with_key(nxt, key) if nxt else None
    logger.debug("%s: fetched %d bars in %d pages", ticker, len(rows), pages)
    return rows


def _upsert_batch(conn, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO market_data_1min (time, ticker, open, high, low, close, volume, vwap, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'massive')
            ON CONFLICT (ticker, time) DO NOTHING
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def _existing_bar_counts(conn, symbols: list[str]) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, COUNT(*) FROM market_data_1min WHERE ticker = ANY(%s) GROUP BY ticker",
            (symbols,),
        )
        return dict(cur.fetchall())


async def backfill(
    symbols: list[str], date_from: str, date_to: str,
    db_url: str, api_key: str, api_base: str,
    *, dry_run: bool = False,
) -> None:
    sync_url = db_url.replace("+asyncpg", "").replace("postgresql://", "postgresql://")
    if sync_url.startswith("postgresql+asyncpg"):
        sync_url = sync_url.replace("postgresql+asyncpg", "postgresql")

    conn = psycopg.connect(sync_url)
    existing = _existing_bar_counts(conn, symbols)

    plan: list[str] = []
    for sym in symbols:
        count = existing.get(sym, 0)
        if count >= 200 * 390:
            logger.info("SKIP %s — already has %d bars (~%d days)", sym, count, count // 390)
        else:
            plan.append(sym)

    logger.info(
        "backfill %s → %s | %d symbols to fetch (skipped %d already populated)",
        date_from, date_to, len(plan), len(symbols) - len(plan),
    )
    if dry_run:
        logger.info("DRY RUN — plan: %s", ", ".join(plan))
        conn.close()
        return
    if not plan:
        logger.info("nothing to do")
        conn.close()
        return

    limiter = _RateLimiter(RATE_PER_SEC)
    sem = asyncio.Semaphore(CONCURRENCY)
    done = {"n": 0, "rows": 0}

    async with httpx.AsyncClient(
        timeout=120.0, headers={"Authorization": f"Bearer {api_key}"}
    ) as client:

        async def worker(sym: str) -> None:
            async with sem:
                try:
                    rows = await _fetch_bars(
                        client, limiter, api_base, api_key, sym, date_from, date_to,
                    )
                except Exception as exc:
                    logger.error("FAILED %s: %r", sym, exc)
                    return
            inserted = _upsert_batch(conn, rows)
            done["n"] += 1
            done["rows"] += inserted
            logger.info("[%d/%d] %s: %d bars fetched, %d upserted", done["n"], len(plan), sym, len(rows), inserted)

        await asyncio.gather(*(worker(sym) for sym in plan))

    conn.close()
    logger.info("DONE — %d symbols, %d total rows inserted", done["n"], done["rows"])


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Backfill market_data_1min from Massive API.")
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--months", type=int, default=12, help="How many months of history (default 12).")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    # Load .env
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    api_key = os.environ.get("MASSIVE_API_KEY", "")
    api_base = os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com")
    db_url = os.environ.get("DATABASE_URL", "postgresql://penguinai:penguinai_dev@localhost:5432/penguinai")

    if not api_key:
        logger.error("MASSIVE_API_KEY not set")
        sys.exit(1)

    symbols = [s.upper() for s in (args.symbols or SYMBOLS)]
    today = datetime.now(UTC).date()
    date_from = (today - timedelta(days=args.months * 30)).isoformat()
    date_to = today.isoformat()

    asyncio.run(backfill(symbols, date_from, date_to, db_url, api_key, api_base, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
