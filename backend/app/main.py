import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin,
    auth,
    earnings,
    market_data,
    signals,
    symbols,
    tickers,
    watchlist,
)
from app.core.config import settings
from app.core.database import init_db

logger = logging.getLogger("app.realtime")
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _start_realtime() -> subprocess.Popen | None:
    """Spawn the realtime ingestion supervisor as a separate process (IBKR stream
    + Massive poller + after-close 30m) so the live data layer comes up with the
    backend, without running heavy ingestion inside the API process. Disable with
    REALTIME_ENABLED=false."""
    if os.getenv("REALTIME_ENABLED", "true").strip().lower() in ("0", "false", "no", "off"):
        logger.info("realtime ingestion disabled (REALTIME_ENABLED)")
        return None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "data.ingestion.realtime.supervisor"], cwd=str(_REPO_ROOT)
        )
        logger.info("realtime ingestion supervisor started (pid=%s)", proc.pid)
        return proc
    except Exception as exc:  # noqa: BLE001 — never block API startup on ingestion
        logger.warning("could not start realtime supervisor: %r", exc)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    proc = _start_realtime()
    try:
        yield
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(symbols.router, prefix="/api/symbols", tags=["symbols"])
app.include_router(tickers.router, prefix="/api/tickers", tags=["tickers"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(market_data.router, prefix="/api/market-data", tags=["market-data"])
app.include_router(earnings.router, prefix="/api/earnings", tags=["earnings"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
