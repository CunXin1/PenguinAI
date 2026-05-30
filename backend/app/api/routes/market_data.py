from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
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
    since = datetime.now(timezone.utc) - timedelta(days=days)

    table_map = {
        "1min": "market_data_1min",
        "30min": "market_data_30min",
        "1day": "market_data_daily",
    }
    table = table_map[timeframe]

    rows = await db.execute(
        text(f"""
            SELECT time, open, high, low, close, volume
            FROM {table}
            WHERE ticker = :ticker AND time >= :since AND adjusted = TRUE
            ORDER BY time ASC
        """),
        {"ticker": ticker, "since": since},
    )
    candles = [
        {"time": row.time.isoformat(), "open": float(row.open), "high": float(row.high),
         "low": float(row.low), "close": float(row.close), "volume": row.volume}
        for row in rows.mappings()
    ]
    return {"ticker": ticker, "timeframe": timeframe, "candles": candles}
