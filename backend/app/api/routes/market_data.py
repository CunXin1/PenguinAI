from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
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
            ),
            base AS (
                SELECT DISTINCT ON (m.ticker) m.ticker, m.open
                FROM market_data_1min m
                JOIN latest l ON l.ticker = m.ticker
                    AND (m.time AT TIME ZONE 'America/New_York')::date
                      = (l.time AT TIME ZONE 'America/New_York')::date
                ORDER BY m.ticker, m.time ASC
            )
            SELECT l.ticker, l.close AS price, l.time, b.open AS base
            FROM latest l
            LEFT JOIN base b ON b.ticker = l.ticker
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
