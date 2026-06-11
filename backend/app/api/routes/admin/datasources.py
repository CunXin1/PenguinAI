from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tier

router = APIRouter()
AdminUser = Depends(require_tier("ADMIN"))

# Last successful F&G fetch older than this reads as stale (the cadence is ≤60 min).
_FNG_STALE_S = 2 * 3600


def _fng_status(h: dict | None) -> str:
    """Derive a health label for the Fear & Greed source from its published state.

    healthy  — recent CNN success
    degraded — CNN unreachable (running on the VIX-proxy fallback) or data stale
    down     — repeated failures / never succeeded
    unknown  — scheduler hasn't run yet
    """
    if not h or not h.get("last_run_at"):
        return "unknown"
    if h.get("consecutive_failures", 0) >= 3 or not h.get("last_success_at"):
        return "down"
    if h.get("source") == "computed":
        return "degraded"
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(h["last_success_at"])).total_seconds()
        if age > _FNG_STALE_S:
            return "degraded"
    except (ValueError, TypeError):
        pass
    return "healthy"

_FRESHNESS_QUERIES: list[tuple[str, str]] = [
    ("market_data_1min", "SELECT max(time) FROM market_data_1min"),
    ("bars_30m", "SELECT max(ts) FROM bars_30m"),
    ("bars_1d", "SELECT max(ts) FROM bars_1d"),
    ("signal_cache", "SELECT max(computed_at) FROM signal_cache"),
    ("social_posts", "SELECT max(time) FROM social_posts"),
    ("celebrity_holdings", "SELECT max(trade_date) FROM celebrity_holdings"),
    ("earnings", "SELECT max(report_date) FROM earnings"),
    ("news_articles", "SELECT max(time) FROM news_articles"),
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

    # 4. Fear & Greed scheduler health (CNN endpoint up? on fallback? stale?)
    fng_health = getattr(request.app.state, "fng_health", None)
    fear_greed = {
        "status": _fng_status(fng_health),
        "source": (fng_health or {}).get("source"),
        "score": (fng_health or {}).get("score"),
        "rating": (fng_health or {}).get("rating"),
        "phase": (fng_health or {}).get("phase"),
        "interval_min": (fng_health or {}).get("interval_min"),
        "consecutive_failures": (fng_health or {}).get("consecutive_failures", 0),
        "last_success_at": (fng_health or {}).get("last_success_at"),
        "last_run_at": (fng_health or {}).get("last_run_at"),
        "next_run_at": (fng_health or {}).get("next_run_at"),
        "last_error": (fng_health or {}).get("last_error"),
    }

    return {
        "realtime": realtime,
        "freshness": freshness,
        "coverage": coverage,
        "fear_greed": fear_greed,
    }
