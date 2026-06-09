import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.database import engine as app_engine
from app.core.market_clock import ET, get_market_status, get_session_phase, ticks_advancing

router = APIRouter()

# Cached market status — avoid hitting SELECT max(time) FROM market_data_1min on every request.
_status_cache: dict = {"data": None, "ts": 0.0}
_status_lock: asyncio.Lock | None = None
_STATUS_CACHE_TTL = 5.0  # seconds


def _get_status_lock() -> asyncio.Lock:
    global _status_lock  # noqa: PLW0603
    if _status_lock is None:
        _status_lock = asyncio.Lock()
    return _status_lock


@router.get("/status")
async def market_status(response: Response, db: AsyncSession = Depends(get_db)):
    """Global "is the US market open right now" — the single source of truth the
    frontend uses for the LIVE/CLOSED badge and to gate live-poll cadence across
    every market-data surface. Public (no auth)."""
    import time

    now_mono = time.monotonic()
    if _status_cache["data"] is not None and (now_mono - _status_cache["ts"]) < _STATUS_CACHE_TTL:
        response.headers["Cache-Control"] = "public, max-age=5"
        return _status_cache["data"]

    async with _get_status_lock():
        now_mono = time.monotonic()
        if (
            _status_cache["data"] is not None
            and (now_mono - _status_cache["ts"]) < _STATUS_CACHE_TTL
        ):
            response.headers["Cache-Control"] = "public, max-age=5"
            return _status_cache["data"]
        result = await get_market_status(db)
        _status_cache["data"] = result
        _status_cache["ts"] = now_mono

    response.headers["Cache-Control"] = "public, max-age=5"
    return result


@router.post("/{ticker}/warm")
async def warm_ticker_endpoint(ticker: str):
    """On-demand: pull a user-opened ticker's recent 1-min bars from Massive into
    market_data_1min (+ indicators) so its chart fills immediately. Idempotent —
    safe to call whenever a chart for an uncovered symbol opens."""
    from data.ingestion.realtime.ondemand import warm_ticker  # lazy: keeps pandas out of import

    n = await warm_ticker(app_engine, ticker)
    return {"ticker": ticker.upper(), "warmed_bars": n}


@router.get("/{ticker}/candles")
async def get_candles(
    ticker: str,
    timeframe: Literal["1min", "30min", "1day"] = Query(default="30min"),
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Return OHLCV bars for charting. Frontend uses TradingView Lightweight Charts."""
    ticker = ticker.upper()
    if timeframe == "1min" and days > 30:
        days = 30
    since = datetime.now(UTC) - timedelta(days=days)

    table_map = {
        "1min": "market_data_1min",
        "30min": "market_data_30min",
        "1day": "market_data_daily",
    }
    table = table_map[timeframe]
    adjusted_filter = " AND adjusted = TRUE" if timeframe == "30min" else ""

    rows = await db.execute(
        text(f"""
            SELECT time, open, high, low, close, volume
            FROM {table}
            WHERE ticker = :ticker AND time >= :since{adjusted_filter}
            ORDER BY time ASC
        """),
        {"ticker": ticker, "since": since},
    )
    candles = [
        {
            "time": row["time"].isoformat(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": row["volume"],
        }
        for row in rows.mappings()
    ]
    return {"ticker": ticker, "timeframe": timeframe, "candles": candles, "count": len(candles)}


@router.get("/quotes")
async def get_quotes(
    db: AsyncSession = Depends(get_db),
    tickers: str = Query(..., description="Comma-separated tickers, e.g. QQQ,SPY,NVDA"),
):
    """Batch latest-quote board: newest 1-min close + % change vs the previous close per ticker.

    Powers the homepage Top-N live board (fed by the IBKR stream → market_data_1min).
    One round-trip for many symbols instead of N candle calls.
    """
    syms = [t.strip().upper() for t in tickers.split(",") if t.strip()][:60]
    if not syms:
        return {"quotes": []}

    rows = await db.execute(
        text("""
            WITH latest AS (
                SELECT DISTINCT ON (ticker) ticker, time, close
                FROM market_data_1min
                WHERE ticker = ANY(:syms)
                ORDER BY ticker, time DESC
            )
            SELECT l.ticker, l.close AS price, l.time, b.close AS base
            FROM latest l
            LEFT JOIN LATERAL (
                -- Previous close: the last bar strictly before the latest bar's ET
                -- session start. "% change today" is measured against the prior close
                -- (not today's open), so a gap shows correctly at the open. Sargable
                -- (ticker, time) backward scan + LIMIT 1 keeps it fast on ~27M rows.
                SELECT m.close
                FROM market_data_1min m
                WHERE m.ticker = l.ticker
                  AND m.time < date_trunc('day', l.time AT TIME ZONE 'America/New_York')
                               AT TIME ZONE 'America/New_York'
                ORDER BY m.time DESC
                LIMIT 1
            ) b ON TRUE
        """),
        {"syms": syms},
    )

    quotes = []
    for row in rows.mappings():
        price = float(row["price"])
        base = float(row["base"]) if row["base"] is not None else price
        change_pct = ((price - base) / base * 100.0) if base else 0.0
        quotes.append(
            {
                "ticker": row["ticker"],
                "price": round(price, 4),
                "change_pct": round(change_pct, 2),
                "time": row["time"].isoformat(),
            }
        )
    return {"quotes": quotes}


@router.get("/mini")
async def get_mini(
    db: AsyncSession = Depends(get_db),
    tickers: str = Query(..., description="Comma-separated tickers, e.g. DIA,QQQ,SPY"),
):
    """Index-strip data: latest price + % change vs previous close + a downsampled
    intraday spark per ticker, batched in one round-trip.

    Powers the homepage market-overview strip. Reads only market_data_1min (fed by the
    IBKR stream). Tickers with no rows are omitted — the frontend renders an empty card.
    """
    syms = [t.strip().upper() for t in tickers.split(",") if t.strip()][:12]
    if not syms:
        return {"items": []}

    # 1) Latest price + previous close per ticker. DISTINCT ON + a LIMIT-1 LATERAL
    #    for the prior close — cheap (same shape as /quotes).
    rows = await db.execute(
        text("""
            WITH latest AS (
                SELECT DISTINCT ON (ticker) ticker, time AS last_t, close AS price
                FROM market_data_1min
                WHERE ticker = ANY(:syms)
                ORDER BY ticker, time DESC
            )
            SELECT l.ticker, l.price, l.last_t, prev.close AS base
            FROM latest l
            LEFT JOIN LATERAL (
                -- Previous close: last bar strictly before the latest bar's ET session
                -- start. "% change today" is vs the prior close (not today's open), so
                -- an open-gap shows correctly. Sargable backward scan + LIMIT 1.
                SELECT m.close
                FROM market_data_1min m
                WHERE m.ticker = l.ticker
                  AND m.time < date_trunc('day', l.last_t AT TIME ZONE 'America/New_York')
                               AT TIME ZONE 'America/New_York'
                ORDER BY m.time DESC
                LIMIT 1
            ) prev ON TRUE
        """),
        {"syms": syms},
    )

    meta: dict[str, dict] = {}
    latest_t: datetime | None = None
    for row in rows.mappings():
        lt = row["last_t"]
        meta[row["ticker"]] = {
            "price": float(row["price"]),
            "base": float(row["base"]) if row["base"] is not None else float(row["price"]),
            "last_t": lt,
        }
        if latest_t is None or lt > latest_t:
            latest_t = lt

    if not meta:
        return {"items": []}

    # 2) Intraday spark for all tickers in ONE scan, bounded by a CONSTANT timestamp
    #    (the latest bar's ET-session start). The correlated form (m.time >= a
    #    per-row LATERAL value) defeated chunk exclusion → a Merge-Append SkipScan
    #    over every chunk (~6s). A plain bind-param bound prunes to one chunk (~0.2s).
    sess_start = (
        latest_t.astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    )
    spark_rows = await db.execute(
        text("""
            SELECT ticker, time_bucket(INTERVAL '5 minutes', time) AS b, last(close, time) AS c
            FROM market_data_1min
            WHERE ticker = ANY(:syms) AND time >= :since
            GROUP BY ticker, b
            ORDER BY ticker, b
        """),
        {"syms": syms, "since": sess_start},
    )

    sparks: dict[str, list[float]] = {}
    for row in spark_rows.mappings():
        if row["c"] is not None:
            sparks.setdefault(row["ticker"], []).append(round(float(row["c"]), 4))

    items = []
    for t in syms:
        m = meta.get(t)
        if m is None:
            continue
        price, base = m["price"], m["base"]
        change_pct = ((price - base) / base * 100.0) if base else 0.0
        items.append(
            {
                "ticker": t,
                "price": round(price, 4),
                "change_pct": round(change_pct, 2),
                "time": m["last_t"].isoformat(),
                "spark": sparks.get(t, [])[-160:],
            }
        )
    return {"items": items}


# Range → (time_bucket size, lookback). All ranges aggregate from the one
# populated table (market_data_1min, 2y of bars) via TimescaleDB time_bucket, so
# the chart shows real data across every range and payload stays bounded
# (1Y → daily candles ~250 bars, not ~340k 1-min rows). Values are timedeltas so
# asyncpg encodes them as PostgreSQL intervals (a bare str fails to bind).
_RANGE_MAP: dict[str, tuple[timedelta, timedelta]] = {
    "1D": (timedelta(minutes=1), timedelta(days=1)),
    "1W": (timedelta(minutes=15), timedelta(days=7)),
    "1M": (timedelta(hours=1), timedelta(days=30)),
    "3M": (timedelta(days=1), timedelta(days=90)),
    "1Y": (timedelta(days=1), timedelta(days=365)),
}


def _bars_from_rows(rows) -> list[dict]:
    """Map an (t, o, h, l, c, v) result set → PriceChart bar dicts (unix-second time)."""
    return [
        {
            "time": int(row["t"].timestamp()),  # unix seconds (UTCTimestamp)
            "open": float(row["o"]),
            "high": float(row["h"]),
            "low": float(row["l"]),
            "close": float(row["c"]),
            "volume": int(row["v"] or 0),
        }
        for row in rows.mappings()
    ]


@router.get("/{ticker}/series")
async def get_series(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    range: str = Query(default="1W", description="1D | 1W | 1M | 3M | 1Y"),
):
    """OHLC series for a user-facing range, time_bucket-aggregated for the PriceChart.

    Two sources, tried in order:
      1. The live minute store (``market_data_1min`` / daily cagg) — freshest, but
         only covers the streamed symbols (~Top-100).
      2. Fallback for the rest of the universe (most of the ~6300 symbols, which
         have imported 30-min/daily bars but no minute data): the
         ``market_data_30min`` view (sub-daily ranges) or ``market_data_daily``
         (3M/1Y). Without this, every 30-min-only symbol charts as empty.

    The fallback window is anchored to the symbol's latest bar (cheap
    ``(instrument_id, ts)`` index lookup on the base hypertable) so a 1–2 day
    stale import still renders every range, including 1D.
    """
    rng = range.upper()
    if rng not in _RANGE_MAP:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"range must be one of {list(_RANGE_MAP)}",
        )
    bucket, lookback = _RANGE_MAP[rng]
    tkr = ticker.upper()
    params = {"bucket": bucket, "lookback": lookback, "ticker": tkr}

    # ── 1) Primary: live minute store ────────────────────────────────────────
    if bucket >= timedelta(days=1):
        # Daily ranges (3M/1Y) read the pre-materialized daily continuous aggregate
        # instead of rescanning ~350k 1-min rows per request (3s → ~10ms).
        primary_sql = """
            SELECT day AS t, open AS o, high AS h, low AS l, close AS c, volume AS v
            FROM market_data_1d_cagg
            WHERE ticker = :ticker AND day >= now() - (:lookback)::interval
            ORDER BY t ASC
        """
    else:
        primary_sql = """
            SELECT time_bucket((:bucket)::interval, time) AS t,
                   first(open, time)  AS o,
                   max(high)          AS h,
                   min(low)           AS l,
                   last(close, time)  AS c,
                   sum(volume)        AS v
            FROM market_data_1min
            WHERE ticker = :ticker AND time >= now() - (:lookback)::interval
            GROUP BY t
            ORDER BY t ASC
        """
    bars = _bars_from_rows(await db.execute(text(primary_sql), params))

    # ── 2) Fallback: imported 30-min / daily bars (covers the whole universe) ──
    if not bars:
        view, base = (
            ("market_data_daily", "bars_1d")
            if bucket >= timedelta(days=1)
            else ("market_data_30min", "bars_30m")
        )
        fallback_sql = f"""
            SELECT time_bucket((:bucket)::interval, m.time) AS t,
                   first(m.open, m.time)  AS o,
                   max(m.high)            AS h,
                   min(m.low)             AS l,
                   last(m.close, m.time)  AS c,
                   sum(m.volume)          AS v
            FROM {view} m
            WHERE m.ticker = :ticker
              AND m.time >= COALESCE(
                  (SELECT max(ts) FROM {base}
                   WHERE instrument_id = (
                       SELECT instrument_id FROM instruments
                       WHERE symbol = :ticker ORDER BY instrument_id LIMIT 1
                   )),
                  now()
              ) - (:lookback)::interval
            GROUP BY t
            ORDER BY t ASC
        """
        try:
            bars = _bars_from_rows(await db.execute(text(fallback_sql), params))
        except Exception:
            bars = []

    return {"ticker": tkr, "range": rng, "bars": bars}


# period → return-horizon column in bars_1d (1D handled live; rest are stored returns)
_PERIOD_RET = {"1W": "ret_5d", "1M": "ret_21d", "3M": "ret_63d", "1Y": "ret_252d"}
_PERIODS = ("1D", *(_PERIOD_RET.keys()))
# Index ETFs shown as tiles up top (ETFs have no market_cap so they aren't in the map).
_INDEX_TILES = (
    ("SPY", "S&P 500"),
    ("QQQ", "Nasdaq 100"),
    ("IWM", "Russell 2000"),
)

# Last 2 daily bars per instrument + the stored return horizons, via the
# (instrument_id, ts) index — cheap.
# NOTE: `{inst}` is a SQL column reference (e.g. "top.instrument_id"), NOT user
# input — the only callers are the heatmap queries below with hardcoded column
# names. Still, mark it clearly so future edits don't pass user strings here.
_DAILY_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT max(adj_close) FILTER (WHERE rn = 1) AS last_close,
               max(adj_close) FILTER (WHERE rn = 2) AS prev_close,
               max(ret_5d)    FILTER (WHERE rn = 1) AS ret_5d,
               max(ret_21d)   FILTER (WHERE rn = 1) AS ret_21d,
               max(ret_63d)   FILTER (WHERE rn = 1) AS ret_63d,
               max(ret_252d)  FILTER (WHERE rn = 1) AS ret_252d
        FROM (
            SELECT adj_close, ret_5d, ret_21d, ret_63d, ret_252d,
                   row_number() OVER (ORDER BY ts DESC) AS rn
            FROM bars_1d WHERE instrument_id = {inst} ORDER BY ts DESC LIMIT 2
        ) x
    ) lc ON TRUE
"""
_ALLOWED_LATERAL_INST = {"top.instrument_id", "i.instrument_id"}


def _daily_lateral(inst: str) -> str:
    if inst not in _ALLOWED_LATERAL_INST:
        raise ValueError(f"invalid lateral column: {inst}")
    return _DAILY_LATERAL.format(inst=inst)


def _period_change(
    m: dict, period: str, is_open: bool, live_price: float | None
) -> tuple[float, float] | None:
    """(price, change_pct) for the selected period, or None if no daily data."""
    if m.get("last_close") is None:
        return None
    last_close = float(m["last_close"])
    if period == "1D":
        prev = float(m["prev_close"]) if m.get("prev_close") is not None else None
        if is_open and live_price is not None:
            price, baseline = live_price, last_close  # intraday move vs prior close
        else:
            price, baseline = last_close, (prev if prev is not None else last_close)
        chg = ((price - baseline) / baseline * 100.0) if baseline else 0.0
    else:
        ret = m.get(_PERIOD_RET[period])  # stored as a fraction
        chg = float(ret) * 100.0 if ret is not None else 0.0
        price = last_close
    return round(price, 2), round(chg, 2)


@router.get("/heatmap")
async def get_heatmap(
    response: Response,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=10, le=500),
    period: str = Query(default="1D", description="1D | 1W | 1M | 3M | 1Y"),
):
    """Market-cap heatmap — tiles sized by market cap, colored by % change over
    the chosen period, plus index ETF tiles (SPY/QQQ/DIA/IWM).

    - 1D: market OPEN → live ``market_data_1min`` price vs prior close; CLOSED →
      last daily close vs the prior session.
    - 1W/1M/3M/1Y: the stored return horizons in ``bars_1d`` (ret_5d/21d/63d/252d).
    """
    period = period.upper()
    if period not in _PERIODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"period must be one of {list(_PERIODS)}",
        )
    now = datetime.now(UTC)
    phase = get_session_phase(now)
    is_open = phase == "REGULAR"
    if not is_open:
        mx = (await db.execute(text("SELECT max(time) FROM market_data_1min"))).scalar()
        is_open = ticks_advancing(mx)

    # ── Top-N by market cap + daily metrics ──────────────────────────────────
    rows = await db.execute(
        text(f"""
            WITH top AS (
                SELECT t.ticker, t.name, t.sector, t.market_cap, i.instrument_id
                FROM tickers t
                JOIN instruments i ON i.symbol = t.ticker
                WHERE t.market_cap IS NOT NULL AND t.is_active
                ORDER BY t.market_cap DESC
                LIMIT :limit
            )
            SELECT top.ticker, top.name, top.sector, top.market_cap,
                   lc.last_close, lc.prev_close, lc.ret_5d, lc.ret_21d, lc.ret_63d, lc.ret_252d
            FROM top
            {_daily_lateral("top.instrument_id")}
            ORDER BY top.market_cap DESC
        """),
        {"limit": limit},
    )
    base = [dict(r) for r in rows.mappings()]

    # ── Index ETF tiles (daily metrics; market_cap N/A for ETFs) ─────────────
    idx_syms = [s for s, _ in _INDEX_TILES]
    idx_rows = await db.execute(
        text(f"""
            SELECT i.symbol, lc.last_close, lc.prev_close,
                   lc.ret_5d, lc.ret_21d, lc.ret_63d, lc.ret_252d
            FROM instruments i
            {_daily_lateral("i.instrument_id")}
            WHERE i.symbol = ANY(:syms)
        """),
        {"syms": idx_syms},
    )
    idx_metrics = {r["symbol"]: dict(r) for r in idx_rows.mappings()}

    # ── Live prices for everything (1D + open only) ──────────────────────────
    live: dict[str, float] = {}
    if is_open and period == "1D":
        syms = [r["ticker"] for r in base] + idx_syms
        lrows = await db.execute(
            text("""
                SELECT DISTINCT ON (ticker) ticker, close
                FROM market_data_1min
                WHERE ticker = ANY(:syms)
                ORDER BY ticker, time DESC
            """),
            {"syms": syms},
        )
        live = {r["ticker"]: float(r["close"]) for r in lrows.mappings()}

    items = []
    for r in base:
        res = _period_change(r, period, is_open, live.get(r["ticker"]))
        if res is None:
            continue
        price, change_pct = res
        items.append(
            {
                "ticker": r["ticker"],
                "name": r["name"],
                "sector": r["sector"],
                "market_cap": int(r["market_cap"]),
                "price": price,
                "change_pct": change_pct,
            }
        )

    indices = []
    for sym, label in _INDEX_TILES:
        m = idx_metrics.get(sym)
        if not m:
            continue
        res = _period_change(m, period, is_open, live.get(sym))
        if res is None:
            continue
        price, change_pct = res
        indices.append({"ticker": sym, "label": label, "price": price, "change_pct": change_pct})

    response.headers["Cache-Control"] = "public, max-age=10" if is_open else "public, max-age=60"
    return {
        "market_open": is_open,
        "as_of": now.isoformat(),
        "period": period,
        "count": len(items),
        "items": items,
        "indices": indices,
    }
