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

    # `base` is the PREVIOUS SESSION's close (the % change reference), taken from the
    # last 1-min print strictly before the latest bar's ET session date — NOT the latest
    # imported daily bar, which can be days stale and would yield a wrong sign/magnitude.
    # Falls back to bars_1d.adj_close only for symbols with no prior-session minute data.
    rows = await db.execute(
        text("""
            WITH latest AS (
                SELECT DISTINCT ON (ticker) ticker, time, close
                FROM market_data_1min
                WHERE ticker = ANY(:syms)
                ORDER BY ticker, time DESC
            )
            SELECT l.ticker, l.close AS price, l.time,
                   COALESCE(p.prev_close, d.adj_close) AS base
            FROM latest l
            JOIN instruments i ON i.symbol = l.ticker
            LEFT JOIN LATERAL (
                SELECT m.close AS prev_close
                FROM market_data_1min m
                WHERE m.ticker = l.ticker
                  AND m.time < date_trunc('day', l.time AT TIME ZONE 'America/New_York')
                               AT TIME ZONE 'America/New_York'
                  AND (m.time AT TIME ZONE 'America/New_York')::time >= time '09:30'
                  AND (m.time AT TIME ZONE 'America/New_York')::time <  time '16:00'
                ORDER BY m.time DESC LIMIT 1
            ) p ON TRUE
            LEFT JOIN LATERAL (
                SELECT adj_close FROM bars_1d
                WHERE instrument_id = i.instrument_id
                ORDER BY ts DESC LIMIT 1
            ) d ON TRUE
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

    # `base` = previous SESSION close (the % change reference): last 1-min print strictly
    # before the latest bar's ET session date. Using the latest imported daily bar instead
    # (which can be days stale) produced a wrong-signed change_pct on the index strip.
    # Falls back to bars_1d.adj_close for symbols with no prior-session minute data.
    rows = await db.execute(
        text("""
            WITH latest AS (
                SELECT DISTINCT ON (ticker) ticker, time AS last_t, close AS price
                FROM market_data_1min
                WHERE ticker = ANY(:syms)
                ORDER BY ticker, time DESC
            )
            SELECT l.ticker, l.price, l.last_t,
                   COALESCE(p.prev_close, d.adj_close) AS base
            FROM latest l
            JOIN instruments i ON i.symbol = l.ticker
            LEFT JOIN LATERAL (
                SELECT m.close AS prev_close
                FROM market_data_1min m
                WHERE m.ticker = l.ticker
                  AND m.time < date_trunc('day', l.last_t AT TIME ZONE 'America/New_York')
                               AT TIME ZONE 'America/New_York'
                  AND (m.time AT TIME ZONE 'America/New_York')::time >= time '09:30'
                  AND (m.time AT TIME ZONE 'America/New_York')::time <  time '16:00'
                ORDER BY m.time DESC LIMIT 1
            ) p ON TRUE
            LEFT JOIN LATERAL (
                SELECT adj_close FROM bars_1d
                WHERE instrument_id = i.instrument_id
                ORDER BY ts DESC LIMIT 1
            ) d ON TRUE
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
    "1W": (timedelta(minutes=10), timedelta(days=7)),
    "1M": (timedelta(minutes=30), timedelta(days=30)),
    "3M": (timedelta(days=1), timedelta(days=90)),
    "1Y": (timedelta(days=1), timedelta(days=365)),
}

# Indicator columns the chart may request, by what each source actually stores.
# bars_10m / bars_30m / market_data_1min carry the full intraday family incl.
# vwap_day; bars_1d (daily) has the trend/momentum/vol family but NO vwap_day.
_BASE_IND_COLS = frozenset({
    "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "ema_50",
    "macd", "macd_signal", "macd_hist", "rsi_14",
    "bb_mid", "bb_upper", "bb_lower", "bb_pctb", "bb_bw", "atr_14", "obv",
})
_INTRADAY_IND_COLS = _BASE_IND_COLS | {"vwap_day", "ret_1bar"}


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


def _split_bars_indicators(
    rows, ind_cols: list[str]
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Map a result set with (t,o,h,l,c,v) + indicator columns into PriceChart bars
    plus a {indicator: [{time, value}, ...]} dict (NULL indicator values skipped,
    so each series is dense). Empty indicator series are dropped from the result."""
    bars: list[dict] = []
    ind: dict[str, list[dict]] = {c: [] for c in ind_cols}
    for row in rows.mappings():
        t = int(row["t"].timestamp())
        bars.append({
            "time": t,
            "open": float(row["o"]),
            "high": float(row["h"]),
            "low": float(row["l"]),
            "close": float(row["c"]),
            "volume": int(row["v"] or 0),
        })
        for c in ind_cols:
            v = row[c]
            if v is not None:
                ind[c].append({"time": t, "value": float(v)})
    return bars, {c: pts for c, pts in ind.items() if pts}


async def _read_base_bars(
    db: AsyncSession, table: str, iid: int, lookback: timedelta,
    ind_cols: list[str], rth_only: bool,
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Read adj OHLCV + requested indicator columns from a bars_* base table,
    windowed to the symbol's latest bar (so a stale import still renders). The
    indicator column names come from a server-side whitelist, never user free text.
    Returns ([], {}) and rolls back on error so the session stays usable."""
    sel = ("," + ", ".join(ind_cols)) if ind_cols else ""
    rth = " AND rth" if rth_only else ""
    try:
        rows = await db.execute(
            text(f"""
                SELECT ts AS t, adj_open AS o, adj_high AS h, adj_low AS l,
                       adj_close AS c, adj_volume AS v{sel}
                FROM {table}
                WHERE instrument_id = :iid{rth}
                  AND ts >= (SELECT max(ts) FROM {table} WHERE instrument_id = :iid)
                            - (:lookback)::interval
                ORDER BY ts ASC
            """),
            {"iid": iid, "lookback": lookback},
        )
        return _split_bars_indicators(rows, ind_cols)
    except Exception:
        await db.rollback()
        return [], {}


async def _read_1min_bars(
    db: AsyncSession, tkr: str, lookback: timedelta, ind_cols: list[str]
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Read raw 1-min OHLCV + indicator columns (populated by the realtime
    update_indicators writeback) for the 1D range, windowed to the latest tick."""
    sel = ("," + ", ".join(ind_cols)) if ind_cols else ""
    try:
        rows = await db.execute(
            text(f"""
                SELECT time AS t, open AS o, high AS h, low AS l,
                       close AS c, volume AS v{sel}
                FROM market_data_1min
                WHERE ticker = :tkr
                  AND time >= (SELECT max(time) FROM market_data_1min WHERE ticker = :tkr)
                              - (:lookback)::interval
                ORDER BY time ASC
            """),
            {"tkr": tkr, "lookback": lookback},
        )
        return _split_bars_indicators(rows, ind_cols)
    except Exception:
        await db.rollback()
        return [], {}


@router.get("/{ticker}/series")
async def get_series(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    range: str = Query(default="1W", description="1D | 1W | 1M | 3M | 1Y"),
    indicators: str = Query(
        default="", description="Comma-separated indicator columns to overlay, e.g. ema_12,macd,rsi_14"
    ),
):
    """OHLC series + optional precomputed indicators for a user-facing range.

    Each range reads candles AND indicators from the DB-stored bar table at the
    matching granularity — no per-request recomputation:
      1D → market_data_1min (1-min; indicators written back by the realtime
           update_indicators loop), falling back to bars_30m.
      1W → bars_10m (10-min), falling back to bars_30m.
      1M → bars_30m (30-min).
      3M / 1Y → bars_1d (daily), falling back to the minute-derived daily cagg
           (OHLC only) when a symbol has no daily bars.

    Each table's window is anchored to the symbol's latest bar (cheap
    ``(instrument_id, ts)`` index lookup) so a 1–2 day stale import still renders.
    ``indicators`` is whitelisted per source (bars_1d has no vwap_day) before being
    interpolated into SQL — never raw user text.
    """
    rng = range.upper()
    if rng not in _RANGE_MAP:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"range must be one of {list(_RANGE_MAP)}",
        )
    _bucket, lookback = _RANGE_MAP[rng]
    tkr = ticker.upper()
    is_daily = rng in ("3M", "1Y")

    # Whitelist + de-dupe (preserve order) the requested indicator columns.
    allowed = _BASE_IND_COLS if is_daily else _INTRADAY_IND_COLS
    seen: set[str] = set()
    ind_cols = [
        c for c in (s.strip() for s in indicators.split(","))
        if c in allowed and not (c in seen or seen.add(c))
    ]

    iid = (await db.execute(
        text("SELECT instrument_id FROM instruments WHERE symbol = :t ORDER BY instrument_id LIMIT 1"),
        {"t": tkr},
    )).scalar()

    bars: list[dict] = []
    ind: dict[str, list[dict]] = {}

    if is_daily:
        if iid is not None:
            bars, ind = await _read_base_bars(db, "bars_1d", iid, lookback, ind_cols, rth_only=False)
        if not bars:
            # Symbol with no daily bars: minute-derived daily cagg (OHLC only).
            try:
                bars = _bars_from_rows(await db.execute(
                    text("""
                        SELECT day AS t, open AS o, high AS h, low AS l, close AS c, volume AS v
                        FROM market_data_1d_cagg
                        WHERE ticker = :ticker AND day >= now() - (:lookback)::interval
                        ORDER BY t ASC
                    """),
                    {"ticker": tkr, "lookback": lookback},
                ))
            except Exception:
                await db.rollback()
                bars = []
    elif rng == "1M":
        if iid is not None:
            bars, ind = await _read_base_bars(db, "bars_30m", iid, lookback, ind_cols, rth_only=True)
    elif rng == "1W":
        if iid is not None:
            bars, ind = await _read_base_bars(db, "bars_10m", iid, lookback, ind_cols, rth_only=True)
            if not bars:  # no 10-min coverage → coarser 30-min bars
                bars, ind = await _read_base_bars(db, "bars_30m", iid, lookback, ind_cols, rth_only=True)
    else:  # 1D
        bars, ind = await _read_1min_bars(db, tkr, lookback, ind_cols)
        if not bars and iid is not None:  # no minute data → 30-min bars
            bars, ind = await _read_base_bars(db, "bars_30m", iid, lookback, ind_cols, rth_only=True)

    # prev_close = the PREVIOUS SESSION's close (the 1D % change baseline). Same
    # rule as /quotes and /mini: the last RTH 1-min print strictly before the
    # latest minute bar's ET session date — NOT the latest imported daily bar,
    # which can be days stale and yields a wrong-signed/magnitude 1D change.
    # bars_1d.adj_close remains the fallback for symbols with no minute data.
    prev_close: float | None = None
    try:
        row = (await db.execute(
            text("""
                WITH latest AS (
                    SELECT max(time) AS t FROM market_data_1min WHERE ticker = :ticker
                )
                SELECT m.close AS prev_close
                FROM market_data_1min m, latest l
                WHERE l.t IS NOT NULL
                  AND m.ticker = :ticker
                  AND m.time < date_trunc('day', l.t AT TIME ZONE 'America/New_York')
                               AT TIME ZONE 'America/New_York'
                  AND (m.time AT TIME ZONE 'America/New_York')::time >= time '09:30'
                  AND (m.time AT TIME ZONE 'America/New_York')::time <  time '16:00'
                ORDER BY m.time DESC LIMIT 1
            """),
            {"ticker": tkr},
        )).mappings().first()
        if row:
            prev_close = float(row["prev_close"])
    except Exception:
        await db.rollback()

    if prev_close is None:
        try:
            row = (await db.execute(
                text("""
                    SELECT adj_close FROM bars_1d
                    WHERE instrument_id = (
                        SELECT instrument_id FROM instruments
                        WHERE symbol = :ticker ORDER BY instrument_id LIMIT 1
                    )
                    ORDER BY ts DESC LIMIT 1
                """),
                {"ticker": tkr},
            )).mappings().first()
            if row:
                prev_close = float(row["adj_close"])
        except Exception:
            await db.rollback()

    return {"ticker": tkr, "range": rng, "bars": bars, "indicators": ind, "prev_close": prev_close}


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
               max(ts)        FILTER (WHERE rn = 1) AS last_ts,
               max(ret_5d)    FILTER (WHERE rn = 1) AS ret_5d,
               max(ret_21d)   FILTER (WHERE rn = 1) AS ret_21d,
               max(ret_63d)   FILTER (WHERE rn = 1) AS ret_63d,
               max(ret_252d)  FILTER (WHERE rn = 1) AS ret_252d
        FROM (
            SELECT adj_close, ts, ret_5d, ret_21d, ret_63d, ret_252d,
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


def _ny_date(ts) -> object | None:
    """NY-session calendar date for a tz-aware timestamp (UTC-assumed if naive)."""
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(ET).date()


def _period_change(
    m: dict, period: str, is_open: bool, sess: dict | None, today_ny
) -> tuple[float, float] | None:
    """(price, change_pct) for the selected period, or None if no daily data.

    1D is always measured against the PRIOR CLOSE (the broker/Finviz convention):
      - if the current session is live (market open) or just-closed but not yet settled
        into ``bars_1d`` → take its price from today's ``market_data_1min`` prints and
        compare to the last settled daily close;
      - otherwise (already settled, or no session today — weekend/holiday/pre-open) →
        last settled close vs the one before it. This branch is fully static, so the
        map freezes outside market hours.

    Stale ticks can't leak in: ``sess`` only carries *today's* RTH prints, so a symbol
    with no fresh data falls through to the settled-bar branch instead of colouring off
    a days-old quote.
    """
    if m.get("last_close") is None:
        return None
    last_close = float(m["last_close"])
    if period == "1D":
        prev = float(m["prev_close"]) if m.get("prev_close") is not None else None
        last_bar_is_today = _ny_date(m.get("last_ts")) == today_ny
        live = sess.get("live") if sess else None  # latest print today (RTH or after-hrs)
        rth_close = sess.get("rth_close") if sess else None  # today's <16:00 close
        if live is not None and not last_bar_is_today:
            # Unsettled current session vs the last settled close. While open use the
            # live print; once closed freeze at today's regular-session (16:00) close.
            baseline = last_close
            price = live if is_open else (rth_close if rth_close is not None else live)
        else:
            # Settled session (or none today) → standard close vs prior close, static.
            baseline = prev if prev is not None else last_close
            price = last_close
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
    the chosen period, plus index ETF tiles (SPY/QQQ/IWM).

    - 1D: always vs PRIOR CLOSE. OPEN → live ``market_data_1min`` price vs prior
      close; CLOSED → the last completed session (today's if it just closed, else
      the prior one) close vs prior close. Frozen outside market hours.
    - 1W/1M/3M/1Y: the stored return horizons in ``bars_1d`` (ret_5d/21d/63d/252d).
    """
    period = period.upper()
    if period not in _PERIODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"period must be one of {list(_PERIODS)}",
        )
    now = datetime.now(UTC)
    today_ny = now.astimezone(ET).date()
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
                   lc.last_close, lc.prev_close, lc.last_ts,
                   lc.ret_5d, lc.ret_21d, lc.ret_63d, lc.ret_252d
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
            SELECT i.symbol, lc.last_close, lc.prev_close, lc.last_ts,
                   lc.ret_5d, lc.ret_21d, lc.ret_63d, lc.ret_252d
            FROM instruments i
            {_daily_lateral("i.instrument_id")}
            WHERE i.symbol = ANY(:syms)
        """),
        {"syms": idx_syms},
    )
    idx_metrics = {r["symbol"]: dict(r) for r in idx_rows.mappings()}

    # ── Today's session prices from the live stream (1D only) ────────────────
    # One row per symbol carrying ONLY today's RTH prints: the latest (open-market
    # live price) and the 16:00 close (freezes the map the instant the session ends,
    # before freshness settles today's bar into bars_1d). Scoping to today's session
    # is also what stops a stale prior-day tick from posing as a "live" price.
    session: dict[str, dict] = {}
    if period == "1D":
        syms = [r["ticker"] for r in base] + idx_syms
        srows = await db.execute(
            text("""
                SELECT ticker,
                       last(close, time)                                  AS live_px,
                       last(close, time) FILTER (WHERE et < time '16:00') AS rth_close_px
                FROM (
                    SELECT ticker, close, time,
                           (time AT TIME ZONE 'America/New_York')::time AS et,
                           (time AT TIME ZONE 'America/New_York')::date AS ed
                    FROM market_data_1min
                    WHERE ticker = ANY(:syms)
                      AND time >= now() - interval '36 hours'
                ) s
                WHERE ed = (now() AT TIME ZONE 'America/New_York')::date
                  AND et >= time '09:30'
                GROUP BY ticker
            """),
            {"syms": syms},
        )
        session = {
            r["ticker"]: {
                "live": float(r["live_px"]) if r["live_px"] is not None else None,
                "rth_close": float(r["rth_close_px"]) if r["rth_close_px"] is not None else None,
            }
            for r in srows.mappings()
        }

    items = []
    for r in base:
        res = _period_change(r, period, is_open, session.get(r["ticker"]), today_ny)
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
        res = _period_change(m, period, is_open, session.get(sym), today_ny)
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
