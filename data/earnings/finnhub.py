"""Finnhub (free tier) → ``earnings`` table ingestion.

WHAT: a one-shot loader that pulls the **earnings calendar** for a date window
from Finnhub and upserts each row into the relational ``earnings`` table. The
FastAPI ``/api/earnings/calendar`` endpoint reads from that table, so the
frontend ``/earnings`` page switches from demo data to live data once this has
run.

HOW Finnhub works here (FREE tier — no paid add-ons required):
  * Endpoint: ``GET /calendar/earnings?from=YYYY-MM-DD&to=YYYY-MM-DD&token=KEY``.
    One call returns the whole US calendar for the window (every symbol), so we
    do NOT fan out per ticker — that keeps us far under the free-tier limit of
    ~60 requests/minute.
  * Each row carries: ``symbol``, ``date``, ``epsEstimate``, ``epsActual``,
    ``revenueEstimate``, ``revenueActual``, ``hour`` ("bmo"/"amc"/"dmh"),
    ``quarter``, ``year``. Free tier does NOT include guidance text or the
    surprise %, so we compute ``eps_surprise_pct`` ourselves when both EPS
    values are present.
  * Free tier caps how far the window may reach; chunk large ranges with
    ``--chunk-days`` (default 90) — each chunk is one request.

FK NOTE: ``earnings.ticker`` references ``tickers(ticker)``. Finnhub returns the
entire market, so we filter to symbols already present in ``tickers`` before
upserting — otherwise the insert would violate the foreign key. Run
``scripts/bootstrap_universe.py`` first to populate the universe.

PIPELINE: HTTP calendar request → filter to known tickers → compute surprise %
→ ``INSERT ... ON CONFLICT (ticker, report_date) DO UPDATE`` (idempotent; a
re-run after results are published fills in actuals).

RUN (from repo root, with .env present and Postgres up):
    python -m data.earnings.finnhub
    python -m data.earnings.finnhub --days-back 7 --days-ahead 30
    python -m data.earnings.finnhub --from 2026-01-01 --to 2026-03-31
    make fetch-earnings

Requires FINNHUB_API_KEY in .env (free key from finnhub.io). This loader cannot
be exercised without that key and a reachable TimescaleDB/Postgres.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("finnhub_earnings")

# ── SQL ──────────────────────────────────────────────────────────────────────
# Self-heal the schema for DBs created before report_hour existed (same
# IF NOT EXISTS idiom the IBKR stream uses for its unique index).
_ENSURE_COLUMN_SQL = text("ALTER TABLE earnings ADD COLUMN IF NOT EXISTS report_hour TEXT")
_UNIVERSE_SQL = text("SELECT ticker FROM tickers")
_UPSERT_SQL = text(
    """
    INSERT INTO earnings (
        ticker, report_date, eps_actual, eps_estimate, eps_surprise_pct,
        revenue_actual, revenue_estimate, guidance_text, report_hour
    )
    VALUES (
        :ticker, :report_date, :eps_actual, :eps_estimate, :eps_surprise_pct,
        :revenue_actual, :revenue_estimate, :guidance_text, :report_hour
    )
    ON CONFLICT (ticker, report_date) DO UPDATE SET
        eps_actual       = EXCLUDED.eps_actual,
        eps_estimate     = EXCLUDED.eps_estimate,
        eps_surprise_pct = EXCLUDED.eps_surprise_pct,
        revenue_actual   = EXCLUDED.revenue_actual,
        revenue_estimate = EXCLUDED.revenue_estimate,
        -- never overwrite existing guidance with a calendar NULL
        guidance_text    = COALESCE(EXCLUDED.guidance_text, earnings.guidance_text),
        report_hour      = EXCLUDED.report_hour
    """
)


# ── Config ───────────────────────────────────────────────────────────────────
class LoaderSettings(BaseSettings):
    """Env-backed defaults (reads the repo-root .env, like the rest of the app)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
    FINNHUB_API_KEY: str = ""
    FINNHUB_BASE_URL: str = "https://finnhub.io/api/v1"


@dataclass(slots=True)
class LoaderConfig:
    api_key: str
    base_url: str
    database_url: str
    date_from: date
    date_to: date
    chunk_days: int
    timeout: float


# ── Calendar fetch ─────────────────────────────────────────────────────────────
def _chunks(start: date, end: date, chunk_days: int) -> list[tuple[date, date]]:
    """Split [start, end] into <=chunk_days windows (one Finnhub request each)."""
    out: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        last = min(cur + timedelta(days=chunk_days - 1), end)
        out.append((cur, last))
        cur = last + timedelta(days=1)
    return out


def _surprise_pct(actual: float | None, estimate: float | None) -> float | None:
    """Conventional EPS surprise % = (actual - estimate) / |estimate| * 100."""
    if actual is None or estimate is None or estimate == 0:
        return None
    return round((actual - estimate) / abs(estimate) * 100.0, 4)


def _to_row(item: dict) -> dict | None:
    """Map one Finnhub earningsCalendar entry to an upsert param dict."""
    symbol = (item.get("symbol") or "").strip().upper()
    raw_date = item.get("date")
    if not symbol or not raw_date:
        return None
    try:
        report_date = date.fromisoformat(str(raw_date))
    except ValueError:
        return None

    eps_actual = item.get("epsActual")
    eps_estimate = item.get("epsEstimate")
    hour = (item.get("hour") or "").strip().lower() or None
    return {
        "ticker": symbol,
        "report_date": report_date,
        "eps_actual": eps_actual,
        "eps_estimate": eps_estimate,
        "eps_surprise_pct": _surprise_pct(eps_actual, eps_estimate),
        "revenue_actual": item.get("revenueActual"),
        "revenue_estimate": item.get("revenueEstimate"),
        "guidance_text": None,  # not provided on the free calendar endpoint
        "report_hour": hour,
    }


async def _fetch_window(
    client: httpx.AsyncClient, cfg: LoaderConfig, start: date, end: date
) -> list[dict]:
    """One free-tier calendar request for [start, end]; returns parsed rows."""
    resp = await client.get(
        f"{cfg.base_url}/calendar/earnings",
        params={"from": start.isoformat(), "to": end.isoformat(), "token": cfg.api_key},
    )
    if resp.status_code == 401:
        raise RuntimeError("Finnhub rejected the API key (401) — check FINNHUB_API_KEY")
    if resp.status_code == 429:
        raise RuntimeError("Finnhub rate limit hit (429) — free tier is ~60 req/min")
    resp.raise_for_status()
    raw = resp.json().get("earningsCalendar") or []
    rows = [r for r in (_to_row(it) for it in raw) if r is not None]
    logger.info("  %s → %s: %d calendar rows", start, end, len(rows))
    return rows


# ── DB ───────────────────────────────────────────────────────────────────────
async def _load_universe(engine) -> set[str]:
    async with engine.connect() as conn:
        result = await conn.execute(_UNIVERSE_SQL)
        return {row[0] for row in result}


async def _upsert(engine, rows: list[dict]) -> None:
    async with engine.begin() as conn:
        await conn.execute(_UPSERT_SQL, rows)


# ── Run ──────────────────────────────────────────────────────────────────────
async def run_loader(cfg: LoaderConfig) -> int:
    engine = create_async_engine(cfg.database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(_ENSURE_COLUMN_SQL)

        universe = await _load_universe(engine)
        if not universe:
            logger.warning(
                "tickers table is empty — run scripts/bootstrap_universe.py first; "
                "nothing to upsert (earnings.ticker has an FK to tickers)"
            )
            return 0
        logger.info("universe: %d known tickers", len(universe))

        windows = _chunks(cfg.date_from, cfg.date_to, cfg.chunk_days)
        logger.info(
            "fetching earnings calendar %s..%s in %d window(s)",
            cfg.date_from,
            cfg.date_to,
            len(windows),
        )

        # de-dupe across windows by (ticker, report_date); keep the latest seen
        merged: dict[tuple[str, date], dict] = {}
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            for start, end in windows:
                for row in await _fetch_window(client, cfg, start, end):
                    if row["ticker"] in universe:
                        merged[(row["ticker"], row["report_date"])] = row

        rows = list(merged.values())
        if not rows:
            logger.info("no rows matched the universe — nothing to upsert")
            return 0

        # batched upsert (keeps the parameter set well-bounded)
        written = 0
        for i in range(0, len(rows), 500):
            batch = rows[i : i + 500]
            await _upsert(engine, batch)
            written += len(batch)
        reported = sum(1 for r in rows if r["eps_actual"] is not None)
        logger.info(
            "upserted %d earnings rows (%d reported, %d upcoming)",
            written,
            reported,
            written - reported,
        )
        return written
    finally:
        await engine.dispose()


async def run_default(days_back: int = 7, days_ahead: int = 30, chunk_days: int = 90) -> int:
    """Scheduler entrypoint (used by the Celery ``fetch_earnings`` task).

    Builds a window of ``today - days_back .. today + days_ahead`` from the
    repo-root ``.env`` config and runs the loader. Raises ``RuntimeError`` when
    ``FINNHUB_API_KEY`` is unset so the caller can log-and-skip.
    """
    s = LoaderSettings()
    if not s.FINNHUB_API_KEY:
        raise RuntimeError("FINNHUB_API_KEY is not set — cannot fetch earnings")
    today = datetime.now(UTC).date()
    cfg = LoaderConfig(
        api_key=s.FINNHUB_API_KEY,
        base_url=s.FINNHUB_BASE_URL,
        database_url=s.DATABASE_URL,
        date_from=today - timedelta(days=days_back),
        date_to=today + timedelta(days=days_ahead),
        chunk_days=max(1, chunk_days),
        timeout=30.0,
    )
    return await run_loader(cfg)


# ── CLI ──────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Load the Finnhub (free tier) earnings calendar into the earnings table."
    )
    p.add_argument("--from", dest="date_from", default=None, help="Start date YYYY-MM-DD.")
    p.add_argument("--to", dest="date_to", default=None, help="End date YYYY-MM-DD.")
    p.add_argument(
        "--days-back", type=int, default=7, help="Window start = today - N (if no --from)."
    )
    p.add_argument(
        "--days-ahead", type=int, default=30, help="Window end = today + N (if no --to)."
    )
    p.add_argument("--chunk-days", type=int, default=90, help="Max days per Finnhub request.")
    p.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout (seconds).")
    p.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    p.add_argument("--api-key", default=None, help="Override FINNHUB_API_KEY.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    s = LoaderSettings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    api_key = args.api_key or s.FINNHUB_API_KEY
    if not api_key:
        logger.error("no Finnhub key — set FINNHUB_API_KEY in .env or pass --api-key")
        return

    today = datetime.now(UTC).date()
    date_from = (
        date.fromisoformat(args.date_from)
        if args.date_from
        else today - timedelta(days=args.days_back)
    )
    date_to = (
        date.fromisoformat(args.date_to)
        if args.date_to
        else today + timedelta(days=args.days_ahead)
    )
    if date_to < date_from:
        logger.error("--to (%s) is before --from (%s)", date_to, date_from)
        return

    cfg = LoaderConfig(
        api_key=api_key,
        base_url=s.FINNHUB_BASE_URL,
        database_url=args.database_url or s.DATABASE_URL,
        date_from=date_from,
        date_to=date_to,
        chunk_days=max(1, args.chunk_days),
        timeout=args.timeout,
    )
    logger.info("Finnhub earnings → earnings table | %s..%s", cfg.date_from, cfg.date_to)
    try:
        asyncio.run(run_loader(cfg))
    except KeyboardInterrupt:
        logger.info("interrupted — shutting down")


if __name__ == "__main__":
    main()
