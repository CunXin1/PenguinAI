"""Validate user-requested symbols against Massive (Polygon-compatible).

A search for a symbol outside our universe is logged in ``symbol_requests``
(status ``pending``) by the backend. This task drains that queue and classifies
each symbol via Massive's reference API:

    real_pending_ingest : Massive knows it and it is active → we just lack data
    delisted            : Massive knows it but it is inactive/delisted
    rejected_junk       : Massive has no record → typo / non-existent

It only writes the classification back to ``symbol_requests`` — it does NOT
backfill bars or promote into ``tickers`` (that is a separate, heavier step).
"""

import asyncio
import logging

import httpx
from sqlalchemy import text

from ml.core.config import ml_settings
from ml.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 15.0
_BATCH = 50  # symbols validated per task run


@celery_app.task(
    name="ml.tasks.symbol_validation.validate_symbol_requests",
    queue="default",
)
def validate_symbol_requests():
    """Classify pending symbol requests via Massive reference API."""
    asyncio.run(_async_validate())


async def _massive_lookup(client: httpx.AsyncClient, base: str, symbol: str) -> dict | None:
    """Return the Massive reference record for ``symbol`` or None if unknown.

    Queries active tickers first, then delisted, so we can tell 'real but
    delisted' apart from 'does not exist'.
    """
    for active in ("true", "false"):
        url = f"{base}/v3/reference/tickers"
        params = {"ticker": symbol, "active": active, "limit": 1}
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as e:
            logger.warning("Massive lookup failed for %s (active=%s): %s", symbol, active, e)
            return None
        if resp.status_code == 429:
            logger.warning("Massive rate-limited on %s", symbol)
            await asyncio.sleep(1.0)
            continue
        if resp.status_code != 200:
            continue
        results = (resp.json() or {}).get("results") or []
        if results:
            return results[0]
    return None


def _classify(record: dict | None) -> tuple[str, str | None, str | None, str | None]:
    """Map a Massive record → (status, name, exchange, note)."""
    if record is None:
        return "rejected_junk", None, None, "no Massive reference match"
    name = record.get("name")
    exchange = record.get("primary_exchange")
    note = record.get("type")  # e.g. CS (common stock), ETF, ...
    if record.get("active") is True and not record.get("delisted_utc"):
        return "real_pending_ingest", name, exchange, note
    return "delisted", name, exchange, note


async def _async_validate():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    if not ml_settings.MASSIVE_API_KEY:
        logger.error("MASSIVE_API_KEY is empty — cannot validate symbol requests")
        return

    engine = create_async_engine(ml_settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT symbol FROM symbol_requests "
                    "WHERE status = 'pending' "
                    "ORDER BY request_count DESC LIMIT :lim"
                ),
                {"lim": _BATCH},
            )
        ).all()
        symbols = [r[0] for r in rows]

    if not symbols:
        logger.info("No pending symbol requests to validate")
        await engine.dispose()
        return

    logger.info("Validating %d pending symbol request(s)", len(symbols))
    headers = {"Authorization": f"Bearer {ml_settings.MASSIVE_API_KEY}"}
    base = ml_settings.MASSIVE_BASE_URL.rstrip("/")

    async with (
        httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=headers) as client,
        SessionLocal() as db,
    ):
        for symbol in symbols:
            record = await _massive_lookup(client, base, symbol)
            status_, name, exchange, note = _classify(record)
            await db.execute(
                text(
                    "UPDATE symbol_requests SET "
                    "status = :status, resolved_name = :name, "
                    "resolved_exchange = :exchange, note = :note, "
                    "validated_at = NOW() "
                    "WHERE symbol = :symbol"
                ),
                {
                    "status": status_,
                    "name": name,
                    "exchange": exchange,
                    "note": note,
                    "symbol": symbol,
                },
            )
            logger.info("Symbol %s → %s", symbol, status_)
        await db.commit()

    await engine.dispose()
