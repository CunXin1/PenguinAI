"""
Seed critical market data on from-zero startup.

Flow:  check DB → check local parquets → fetch from Massive API.
Only runs when bars_30m has zero rows for the seed tickers.
Designed to run as a background thread (non-blocking).

IMPORTANT: This module runs in a BACKGROUND THREAD with its own event loop
(via asyncio.run). It must NOT reuse the main thread's AsyncSessionLocal/engine
because asyncpg pools are bound to the event loop that created them. Instead,
_make_session() creates a fresh engine per call.

NOTE: Massive API path provides OHLCV only (no indicators). Charts will work
but ML signal quality remains NEUTRAL until a full import (make import-30min)
populates indicator columns. The parquet path includes pre-computed indicators.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger("app.seed")

ET = ZoneInfo("America/New_York")
_REPO_ROOT = Path(__file__).resolve().parents[3]
_30M_DIR = _REPO_ROOT / "data" / "30min_data"
_DAILY_DIR = _REPO_ROOT / "data" / "daily_data"

# Keep ETF set in sync with data/ingestion/massive_30min_parquet._classify_asset.
_ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "GLD", "XLF", "XLK", "ARKK",
    "IVV", "VUG", "VEA", "VTV", "IEFA", "BND", "AGG", "IWF", "IJH", "IEMG",
    "VWO", "IJR", "VIG", "VXUS", "TLT",
}


def _asset_type(ticker: str) -> str:
    return "etf" if ticker in _ETFS else "stock"


def _get_seed_tickers() -> list[str]:
    """Derive seed tickers from bootstrap_universe (single source of truth)."""
    try:
        from scripts.bootstrap_universe import TICKER_UNIVERSE

        return [t["ticker"] for t in TICKER_UNIVERSE]
    except Exception:
        return [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
            "AMD", "PLTR", "NFLX", "JPM", "V",
            "SPY", "QQQ", "IWM", "DIA", "GLD",
        ]


def _make_session() -> tuple[async_sessionmaker[AsyncSession], any]:
    """Create a fresh engine + session factory for THIS event loop."""
    from app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL, pool_size=5, pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory, engine


# ---------------------------------------------------------------------------
# Step 1: Check DB
# ---------------------------------------------------------------------------


async def _db_has_seed_bars(session_factory, tickers: list[str]) -> bool:
    async with session_factory() as db:
        result = await db.execute(
            text(
                "SELECT EXISTS("
                "  SELECT 1 FROM instruments i"
                "  JOIN bars_30m b ON b.instrument_id = i.instrument_id"
                "  WHERE i.symbol = ANY(:tickers)"
                ")"
            ),
            {"tickers": tickers},
        )
        return bool(result.scalar_one())


# ---------------------------------------------------------------------------
# Step 2: Find local parquets
# ---------------------------------------------------------------------------


def _find_parquets(tickers: list[str]) -> dict[str, tuple[Path | None, Path | None]]:
    """Return {ticker: (30m_path_or_None, daily_path_or_None)}."""
    found: dict[str, tuple[Path | None, Path | None]] = {}
    for t in tickers:
        asset = _asset_type(t)
        p30 = _30M_DIR / asset / f"{t}.parquet"
        pd = _DAILY_DIR / asset / f"{t}.parquet"
        f30 = p30 if p30.exists() else None
        fd = pd if pd.exists() else None
        if f30 or fd:
            found[t] = (f30, fd)
    return found


# ---------------------------------------------------------------------------
# Step 3a: Import from parquets
# ---------------------------------------------------------------------------

_30M_DB_COLS = [
    "ts", "instrument_id", "rth",
    "raw_open", "raw_high", "raw_low", "raw_close", "raw_volume",
    "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
    "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "ema_50",
    "macd", "macd_signal", "macd_hist", "rsi_14",
    "bb_mid", "bb_upper", "bb_lower", "bb_pctb", "bb_bw",
    "atr_14", "obv", "vwap_day", "ret_1bar",
]

_1D_DB_COLS = [
    "ts", "instrument_id", "rth_bars", "raw_close",
    "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
    "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "ema_50",
    "macd", "macd_signal", "macd_hist", "rsi_14",
    "bb_mid", "bb_upper", "bb_lower", "bb_pctb", "bb_bw",
    "atr_14", "obv",
    "ret_1d", "ret_5d", "ret_21d", "ret_63d", "ret_126d", "ret_252d",
    "gap_overnight",
]


async def _ensure_instrument(db, symbol: str, asset_type: str) -> int:
    result = await db.execute(
        text(
            "INSERT INTO instruments (symbol, asset_type)"
            " VALUES (:s, :a) ON CONFLICT (symbol, asset_type) DO NOTHING"
            " RETURNING instrument_id"
        ),
        {"s": symbol, "a": asset_type},
    )
    row = result.first()
    if row:
        return row[0]
    result = await db.execute(
        text("SELECT instrument_id FROM instruments WHERE symbol = :s AND asset_type = :a"),
        {"s": symbol, "a": asset_type},
    )
    return result.scalar_one()


async def _import_parquets(
    session_factory,
    parquets: dict[str, tuple[Path | None, Path | None]],
    stop: threading.Event,
) -> int:
    import pyarrow.parquet as pq

    total = 0
    for ticker, (p30, pd) in parquets.items():
        if stop.is_set():
            logger.info("seed: stop requested, aborting parquet import")
            break

        async with session_factory() as db:
            asset = _asset_type(ticker)
            iid = await _ensure_instrument(db, ticker, asset)

            if p30:
                try:
                    t = pq.read_table(p30)
                    n = await _load_arrow(db, t, "bars_30m", _30M_DB_COLS, iid, ts_col="ts")
                    total += n
                    logger.info("seed: imported %s 30m parquet (%d bars)", ticker, n)
                except Exception:
                    logger.warning("seed: failed to import 30m parquet for %s", ticker, exc_info=True)

            if pd:
                try:
                    t = pq.read_table(pd)
                    ts_col = "last_ts" if "last_ts" in set(t.column_names) else "date"
                    n = await _load_arrow(db, t, "bars_1d", _1D_DB_COLS, iid, ts_col=ts_col)
                    total += n
                    logger.info("seed: imported %s daily parquet (%d bars)", ticker, n)
                except Exception:
                    logger.warning("seed: failed to import daily parquet for %s", ticker, exc_info=True)

            await db.commit()
    return total


async def _load_arrow(
    db, table, target_table: str, db_cols: list[str], instrument_id: int, *, ts_col: str = "ts"
) -> int:
    """Generic parquet → DB loader for both 30m and 1d tables."""
    col_names = set(table.column_names)
    rows = table.to_pydict()
    n = table.num_rows
    if n == 0:
        return 0

    placeholders = ", ".join(f":{c}" for c in db_cols)
    cols_sql = ", ".join(db_cols)
    sql = text(
        f"INSERT INTO {target_table} ({cols_sql}) VALUES ({placeholders})"
        " ON CONFLICT (ts, instrument_id) DO NOTHING"
    )

    ts_data = rows[ts_col]
    col_data = {}
    for c in db_cols:
        if c in ("ts", "instrument_id"):
            continue
        col_data[c] = rows[c] if c in col_names else None

    batch = []
    for i in range(n):
        row = {"instrument_id": instrument_id, "ts": ts_data[i]}
        for c, data in col_data.items():
            row[c] = data[i] if data is not None else None
        batch.append(row)

        if len(batch) >= 2000:
            await db.execute(sql, batch)
            batch = []

    if batch:
        await db.execute(sql, batch)
    return n


# ---------------------------------------------------------------------------
# Step 3b: Fetch from Massive API
# ---------------------------------------------------------------------------

_PAGE_LIMIT = 50_000


async def _fetch_from_massive(
    session_factory, api_key: str, base_url: str, tickers: list[str], stop: threading.Event
) -> int:
    import httpx

    today = date.today()
    from_30m = (today - timedelta(days=30)).isoformat()
    from_1d = (today - timedelta(days=400)).isoformat()
    to = today.isoformat()

    total_bars = 0
    tickers_done = 0
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    ) as client:
        for ticker in tickers:
            if stop.is_set():
                logger.info("seed: stop requested, aborting Massive fetch")
                break

            async with session_factory() as db:
                asset = _asset_type(ticker)
                iid = await _ensure_instrument(db, ticker, asset)

                try:
                    n = await _fetch_and_write_30m(
                        client, db, api_key, base_url, ticker, iid, from_30m, to
                    )
                    total_bars += n
                except Exception:
                    logger.warning("seed: Massive 30m fetch failed for %s", ticker, exc_info=True)

                try:
                    n = await _fetch_and_write_1d(
                        client, db, api_key, base_url, ticker, iid, from_1d, to
                    )
                    total_bars += n
                except Exception:
                    logger.warning("seed: Massive daily fetch failed for %s", ticker, exc_info=True)

                await db.commit()

            tickers_done += 1
            logger.info("seed: %d/%d tickers done (%s)", tickers_done, len(tickers), ticker)

    return total_bars


async def _massive_get(client, url: str) -> dict | None:
    for attempt in range(4):
        try:
            resp = await client.get(url)
        except Exception:
            if attempt == 3:
                raise
            await asyncio.sleep(2**attempt)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == 3:
                resp.raise_for_status()
            await asyncio.sleep(min(2**attempt, 15))
            continue
        resp.raise_for_status()
        return resp.json()
    return None


async def _fetch_series(
    client, base_url: str, api_key: str,
    ticker: str, interval: str, date_from: str, date_to: str, *, adjusted: bool,
) -> dict[int, tuple]:
    adj = "true" if adjusted else "false"
    url: str | None = (
        f"{base_url}/v2/aggs/ticker/{ticker}/range/{interval}"
        f"/{date_from}/{date_to}?adjusted={adj}&sort=asc&limit={_PAGE_LIMIT}"
    )
    out: dict[int, tuple] = {}
    while url:
        data = await _massive_get(client, url)
        if not data:
            break
        for r in data.get("results") or []:
            t = r.get("t")
            o, h, lo, c = r.get("o"), r.get("h"), r.get("l"), r.get("c")
            if t is None or None in (o, h, lo, c):
                continue
            out[int(t)] = (o, h, lo, c, int(round(float(r.get("v") or 0))))
        nxt = data.get("next_url")
        if nxt and not nxt.startswith("http"):
            nxt = f"{base_url}{nxt}"
        url = nxt if nxt else None
    return out


async def _fetch_and_write_30m(client, db, api_key, base_url, ticker, iid, from_d, to_d) -> int:
    raw = await _fetch_series(client, base_url, api_key, ticker, "30/minute", from_d, to_d, adjusted=False)
    adj = await _fetch_series(client, base_url, api_key, ticker, "30/minute", from_d, to_d, adjusted=True)
    if not raw and not adj:
        return 0

    all_t = sorted(set(raw) | set(adj))
    sql = text(
        "INSERT INTO bars_30m (ts, instrument_id, rth,"
        " raw_open, raw_high, raw_low, raw_close, raw_volume,"
        " adj_open, adj_high, adj_low, adj_close, adj_volume)"
        " VALUES (:ts, :iid, :rth,"
        " :ro, :rh, :rl, :rc, :rv, :ao, :ah, :al, :ac, :av)"
        " ON CONFLICT (ts, instrument_id) DO NOTHING"
    )

    batch = []
    for t in all_t:
        ts = datetime.fromtimestamp(t / 1000.0, tz=UTC)
        et = ts.astimezone(ET)
        rth = 0 <= et.weekday() <= 4 and 9 * 60 + 30 <= et.hour * 60 + et.minute < 16 * 60
        r = raw.get(t)
        a = adj.get(t)
        batch.append({
            "ts": ts, "iid": iid, "rth": rth,
            "ro": r[0] if r else None, "rh": r[1] if r else None,
            "rl": r[2] if r else None, "rc": r[3] if r else None,
            "rv": r[4] if r else None,
            "ao": a[0] if a else None, "ah": a[1] if a else None,
            "al": a[2] if a else None, "ac": a[3] if a else None,
            "av": a[4] if a else None,
        })
        if len(batch) >= 1000:
            await db.execute(sql, batch)
            batch = []

    if batch:
        await db.execute(sql, batch)
    return len(all_t)


async def _fetch_and_write_1d(client, db, api_key, base_url, ticker, iid, from_d, to_d) -> int:
    adj = await _fetch_series(client, base_url, api_key, ticker, "1/day", from_d, to_d, adjusted=True)
    if not adj:
        return 0

    sql = text(
        "INSERT INTO bars_1d (ts, instrument_id, adj_open, adj_high, adj_low, adj_close, adj_volume)"
        " VALUES (:ts, :iid, :ao, :ah, :al, :ac, :av)"
        " ON CONFLICT (ts, instrument_id) DO NOTHING"
    )

    batch = []
    for t in sorted(adj):
        ts = datetime.fromtimestamp(t / 1000.0, tz=UTC)
        a = adj[t]
        batch.append({
            "ts": ts, "iid": iid,
            "ao": a[0], "ah": a[1], "al": a[2], "ac": a[3], "av": a[4],
        })
        if len(batch) >= 500:
            await db.execute(sql, batch)
            batch = []

    if batch:
        await db.execute(sql, batch)
    return len(adj)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def _run_seed(stop: threading.Event) -> None:
    tickers = _get_seed_tickers()
    logger.info("seed: checking if critical market data exists for %d tickers...", len(tickers))

    session_factory, engine = _make_session()
    try:
        if await _db_has_seed_bars(session_factory, tickers):
            logger.info("seed: bars_30m already has data for seed tickers — skipping")
            return

        if stop.is_set():
            return

        parquets = _find_parquets(tickers)
        if parquets:
            logger.info("seed: found %d local parquet files — importing...", len(parquets))
            n = await _import_parquets(session_factory, parquets, stop)
            logger.info("seed: imported %d total bars from parquets", n)
            return

        if stop.is_set():
            return

        import os

        api_key = os.getenv("MASSIVE_API_KEY", "")
        base_url = os.getenv("MASSIVE_BASE_URL", "https://api.massive.com")
        if not api_key:
            logger.warning(
                "seed: no parquets found and MASSIVE_API_KEY not set — "
                "charts will be empty until data is loaded manually (make import-30min)"
            )
            return

        logger.info(
            "seed: no parquets found — fetching %d tickers from Massive API "
            "(~30 days 30m + ~1 year daily, OHLCV only — no indicators)...",
            len(tickers),
        )
        n = await _fetch_from_massive(session_factory, api_key, base_url, tickers, stop)
        logger.info("seed: fetched %d total bars from Massive API", n)
    finally:
        await engine.dispose()


def run_seed_thread(stop_event: threading.Event) -> None:
    """Entry point for background thread. Safe to call from main.py lifespan."""
    try:
        asyncio.run(_run_seed(stop_event))
    except Exception:
        logger.warning("seed: market data seed failed", exc_info=True)
