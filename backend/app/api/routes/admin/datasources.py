from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tier

router = APIRouter()
AdminUser = Depends(require_tier("ADMIN"))

_FRESHNESS_QUERIES: list[tuple[str, str]] = [
    ("market_data_1min", "SELECT max(time) FROM market_data_1min"),
    ("bars_30m", "SELECT max(ts) FROM bars_30m"),
    ("bars_1d", "SELECT max(ts) FROM bars_1d"),
    ("signal_cache", "SELECT max(computed_at) FROM signal_cache"),
    ("social_posts", "SELECT max(time) FROM social_posts"),
    ("celebrity_holdings", "SELECT max(trade_date) FROM celebrity_holdings"),
    ("earnings", "SELECT max(report_date) FROM earnings"),
    ("news_articles", "SELECT max(published_at) FROM news_articles"),
]


@router.get("/status")
async def datasource_status(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _=AdminUser,
):
    """Realtime data source connections and data freshness per table."""
    # 1. Realtime services from supervisor watchdog
    realtime = []
    watchdog = getattr(request.app.state, "watchdog", None)
    if watchdog is not None:
        h = watchdog.health
        sv_services = h.get("services", {})
        for svc_name in ("ibkr", "finnhub", "massive", "close30m"):
            svc = sv_services.get(svc_name, {})
            realtime.append(
                {
                    "name": svc_name,
                    "alive": svc.get("alive", False),
                    "uptime_s": svc.get("uptime_s"),
                    "restarts": svc.get("restarts", 0),
                    "detail": svc.get("detail", ""),
                }
            )

    # 2. Data freshness
    freshness = []
    for table, query in _FRESHNESS_QUERIES:
        try:
            result = await db.execute(text(query))
            ts = result.scalar()
            freshness.append(
                {
                    "table": table,
                    "latest_ts": ts.isoformat() if ts else None,
                }
            )
        except Exception:
            freshness.append({"table": table, "latest_ts": None})

    # 3. Symbol coverage
    coverage = {}
    try:
        r = await db.execute(
            text("SELECT count(DISTINCT ticker) FROM market_data_1min")
        )
        coverage["realtime_1min_symbols"] = r.scalar() or 0
    except Exception:
        coverage["realtime_1min_symbols"] = 0

    try:
        r = await db.execute(text("SELECT count(*) FROM instruments"))
        coverage["instruments_total"] = r.scalar() or 0
    except Exception:
        coverage["instruments_total"] = 0

    try:
        r = await db.execute(text("SELECT count(*) FROM tickers WHERE is_active = true"))
        coverage["tickers_active"] = r.scalar() or 0
    except Exception:
        coverage["tickers_active"] = 0

    return {
        "realtime": realtime,
        "freshness": freshness,
        "coverage": coverage,
    }
