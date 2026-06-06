from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db

router = APIRouter()


@router.get("/{ticker}/candles")
async def get_candles(
    ticker: str,
    timeframe: Literal["1min", "30min", "1day"] = Query(default="30min"),
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Return OHLCV bars for charting. Frontend uses TradingView Lightweight Charts."""
    ticker = ticker.upper()
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
    return {"ticker": ticker, "timeframe": timeframe, "candles": candles}


@router.get("/quotes")
async def get_quotes(
    db: AsyncSession = Depends(get_db),
    tickers: str = Query(..., description="Comma-separated tickers, e.g. QQQ,SPY,NVDA"),
):
    """Batch latest-quote board: newest 1-min close + same-session % change per ticker.

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
            SELECT l.ticker, l.close AS price, l.time, b.open AS base
            FROM latest l
            LEFT JOIN LATERAL (
                -- first bar of the latest bar's ET session, found via a sargable
                -- (ticker, time) range scan instead of a full per-ticker date filter
                -- — keeps /quotes fast on a 27M-row market_data_1min.
                SELECT m.open
                FROM market_data_1min m
                WHERE m.ticker = l.ticker
                  AND m.time >= date_trunc('day', l.time AT TIME ZONE 'America/New_York')
                                AT TIME ZONE 'America/New_York'
                  AND m.time <= l.time
                ORDER BY m.time ASC
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
    """Index-strip data: latest price + same-session % change + a downsampled intraday
    spark per ticker, batched in one round-trip.

    Powers the homepage market-overview strip. Reads only market_data_1min (fed by the
    IBKR stream). Tickers with no rows are omitted — the frontend renders an empty card.
    """
    syms = [t.strip().upper() for t in tickers.split(",") if t.strip()][:12]
    if not syms:
        return {"items": []}

    rows = await db.execute(
        text("""
            WITH latest AS (
                SELECT DISTINCT ON (ticker) ticker, time AS last_t, close AS price
                FROM market_data_1min
                WHERE ticker = ANY(:syms)
                ORDER BY ticker, time DESC
            )
            SELECT l.ticker, l.price, l.last_t, base.open AS base, spark.pts AS spark
            FROM latest l
            -- start of the latest bar's ET session (basis for both %chg and the spark)
            CROSS JOIN LATERAL (
                SELECT date_trunc('day', l.last_t AT TIME ZONE 'America/New_York')
                       AT TIME ZONE 'America/New_York' AS sess_start
            ) sess
            LEFT JOIN LATERAL (
                SELECT m.open
                FROM market_data_1min m
                WHERE m.ticker = l.ticker AND m.time >= sess.sess_start AND m.time <= l.last_t
                ORDER BY m.time ASC
                LIMIT 1
            ) base ON TRUE
            LEFT JOIN LATERAL (
                SELECT array_agg(c ORDER BY b) AS pts
                FROM (
                    SELECT time_bucket(INTERVAL '5 minutes', m.time) AS b,
                           last(m.close, m.time) AS c
                    FROM market_data_1min m
                    WHERE m.ticker = l.ticker AND m.time >= sess.sess_start AND m.time <= l.last_t
                    GROUP BY b
                ) q
            ) spark ON TRUE
        """),
        {"syms": syms},
    )

    items = []
    for row in rows.mappings():
        price = float(row["price"])
        base = float(row["base"]) if row["base"] is not None else price
        change_pct = ((price - base) / base * 100.0) if base else 0.0
        # bound the spark payload + drop any nulls from sparse buckets
        spark = [round(float(x), 4) for x in (row["spark"] or []) if x is not None][-160:]
        items.append(
            {
                "ticker": row["ticker"],
                "price": round(price, 4),
                "change_pct": round(change_pct, 2),
                "time": row["last_t"].isoformat(),
                "spark": spark,
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


@router.get("/{ticker}/series")
async def get_series(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    range: str = Query(default="1W", description="1D | 1W | 1M | 3M | 1Y"),
):
    """OHLC series for a user-facing range, time_bucket-aggregated from market_data_1min.

    Powers the shared PriceChart component (dashboard + signal detail). Bucket size
    scales with the range so a year renders as daily candles, not raw minutes.
    """
    rng = range.upper()
    if rng not in _RANGE_MAP:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"range must be one of {list(_RANGE_MAP)}",
        )
    bucket, lookback = _RANGE_MAP[rng]

    if bucket >= timedelta(days=1):
        # Daily ranges (3M/1Y) read the pre-materialized daily continuous aggregate
        # instead of rescanning ~350k 1-min rows per request (3s → ~10ms).
        sql = """
            SELECT day AS t, open AS o, high AS h, low AS l, close AS c, volume AS v
            FROM market_data_1d_cagg
            WHERE ticker = :ticker AND day >= now() - (:lookback)::interval
            ORDER BY t ASC
        """
        params = {"lookback": lookback, "ticker": ticker.upper()}
    else:
        sql = """
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
        params = {"bucket": bucket, "lookback": lookback, "ticker": ticker.upper()}

    rows = await db.execute(text(sql), params)
    bars = [
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
    return {"ticker": ticker.upper(), "range": rng, "bars": bars}
