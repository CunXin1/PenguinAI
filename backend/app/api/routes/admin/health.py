from __future__ import annotations

import asyncio
import time
from datetime import UTC
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tier
from app.core.config import settings
from app.core.database import engine

router = APIRouter()
AdminUser = Depends(require_tier("ADMIN"))


@router.get("/overview")
async def health_overview(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _=AdminUser,
):
    """Traffic-light view of every service in the stack."""
    from datetime import datetime

    services = []

    # 1. TimescaleDB
    try:
        t0 = time.perf_counter()
        result = await db.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database()"
            )
        )
        latency = (time.perf_counter() - t0) * 1000
        active = result.scalar() or 0
        pool = engine.pool
        pool_status = f"pool: {pool.checkedout()}/{pool.size()} active"
        services.append(
            {
                "name": "timescaledb",
                "status": "healthy",
                "latency_ms": round(latency, 1),
                "detail": f"{active} connections, {pool_status}",
            }
        )
    except Exception as exc:
        services.append(
            {
                "name": "timescaledb",
                "status": "down",
                "latency_ms": None,
                "detail": str(exc)[:120],
            }
        )

    # 2. Redis
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        t0 = time.perf_counter()
        pong = await r.ping()
        latency = (time.perf_counter() - t0) * 1000
        info = await r.info("memory")
        mem = info.get("used_memory_human", "?")
        await r.aclose()
        services.append(
            {
                "name": "redis",
                "status": "healthy" if pong else "degraded",
                "latency_ms": round(latency, 1),
                "detail": f"PONG, mem={mem}",
            }
        )
    except Exception as exc:
        services.append(
            {
                "name": "redis",
                "status": "down",
                "latency_ms": None,
                "detail": str(exc)[:120],
            }
        )

    # 3. Backend API (self)
    services.append(
        {
            "name": "backend_api",
            "status": "healthy",
            "latency_ms": None,
            "detail": "serving (self)",
        }
    )

    # 4. Celery workers (inspect is synchronous — run in thread to avoid blocking)
    try:
        from celery import Celery

        def _inspect_celery():
            cel = Celery(broker=settings.REDIS_URL)
            inspector = cel.control.inspect(timeout=2.0)
            return inspector.ping() or {}, inspector.active() or {}

        ping_resp, active_resp = await asyncio.to_thread(_inspect_celery)

        worker_count = len(ping_resp)
        active_count = sum(len(tasks) for tasks in active_resp.values())

        if worker_count > 0:
            services.append(
                {
                    "name": "celery_workers",
                    "status": "healthy",
                    "latency_ms": None,
                    "detail": f"{worker_count} online, {active_count} active tasks",
                }
            )
        else:
            services.append(
                {
                    "name": "celery_workers",
                    "status": "down",
                    "latency_ms": None,
                    "detail": "no workers responding",
                }
            )
    except Exception as exc:
        services.append(
            {
                "name": "celery_workers",
                "status": "down",
                "latency_ms": None,
                "detail": str(exc)[:120],
            }
        )

    # 5. Realtime supervisor + IBKR + Finnhub
    watchdog = getattr(request.app.state, "watchdog", None)
    if watchdog is not None:
        h = watchdog.health
        sv_status = h.get("supervisor", "unknown")
        services.append(
            {
                "name": "realtime_supervisor",
                "status": "healthy" if sv_status == "running" else (
                    "degraded" if sv_status == "disabled" else "down"
                ),
                "latency_ms": None,
                "detail": f"pid={h.get('pid')}, restarts={h.get('restarts', 0)}",
            }
        )

        sv_services = h.get("services", {})
        for svc_name in ("ibkr", "finnhub"):
            svc = sv_services.get(svc_name, {})
            alive = svc.get("alive", False)
            uptime = svc.get("uptime_s", 0)
            restarts = svc.get("restarts", 0)
            services.append(
                {
                    "name": f"{svc_name}_stream",
                    "status": "healthy" if alive else "down",
                    "latency_ms": None,
                    "detail": f"uptime={uptime:.0f}s, restarts={restarts}",
                }
            )
    else:
        for name in ("realtime_supervisor", "ibkr_stream", "finnhub_stream"):
            services.append(
                {"name": name, "status": "down", "latency_ms": None, "detail": "watchdog not available"}
            )

    # Compute overall
    statuses = [s["status"] for s in services]
    critical_services = {"timescaledb", "redis"}
    critical_down = any(
        s["status"] == "down" and s["name"] in critical_services for s in services
    )
    if critical_down:
        overall = "critical"
    elif "down" in statuses or "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "overall": overall,
        "checked_at": datetime.now(UTC).isoformat(),
        "services": services,
    }


@router.get("/endpoints")
async def endpoint_health(request: Request, _=AdminUser):
    """List all registered routes and probe key endpoints."""
    routes = []
    for route in request.app.routes:
        if hasattr(route, "methods"):
            for method in route.methods:
                if method in ("GET", "POST", "PATCH", "PUT", "DELETE"):
                    routes.append(
                        {
                            "method": method,
                            "path": route.path,
                            "name": getattr(route, "name", None),
                        }
                    )

    probes = []
    probe_targets = [
        "/health",
        "/api/market-data/status",
        "/api/signals/top?limit=1",
        "/api/tickers/search?q=AAPL",
    ]
    base = f"{request.base_url.scheme}://{request.base_url.netloc}"
    async with httpx.AsyncClient(base_url=base, timeout=5.0) as client:
        for endpoint in probe_targets:
            try:
                t0 = time.perf_counter()
                resp = await client.get(endpoint)
                latency = (time.perf_counter() - t0) * 1000
                probes.append(
                    {
                        "endpoint": endpoint,
                        "status_code": resp.status_code,
                        "latency_ms": round(latency, 1),
                        "error": None,
                    }
                )
            except Exception as exc:
                probes.append(
                    {
                        "endpoint": endpoint,
                        "status_code": None,
                        "latency_ms": None,
                        "error": str(exc)[:120],
                    }
                )

    return {"routes": routes, "probes": probes}
