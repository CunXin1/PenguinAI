import asyncio
import contextlib
import json
import logging
import os
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin,
    auth,
    celebrity_holdings,
    earnings,
    fomc,
    market_data,
    news,
    signals,
    symbols,
    tickers,
    watchlist,
)
from app.core.config import settings
from app.core.startup import get_startup_report, run_startup_checks

logger = logging.getLogger("app.realtime")
_REPO_ROOT = Path(__file__).resolve().parents[2]

# data/, ml/, scripts/ live at the repo root — make them importable from backend/.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class _SupervisorWatchdog:
    """Monitors the supervisor subprocess: restarts on crash, parses health lines."""

    _MAX_RESTARTS = 10
    _RESTART_WINDOW = 3600.0  # reset restart count after 1 hour of stable uptime

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.enabled = os.getenv("REALTIME_ENABLED", "true").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._restart_count = 0
        self._last_stable_since = monotonic()
        self._last_health: dict | None = None
        self._last_health_at: float = 0

    def start(self) -> None:
        if not self.enabled:
            logger.info("realtime ingestion disabled (REALTIME_ENABLED)")
            return
        self._spawn()
        if self.proc is not None:
            self._thread = threading.Thread(
                target=self._watch_loop, daemon=True, name="sv-watchdog"
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kill_proc()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def health(self) -> dict:
        if not self.enabled:
            return {"supervisor": "disabled"}
        alive = self.proc is not None and self.proc.poll() is None
        h: dict = {
            "supervisor": "running" if alive else "dead",
            "pid": self.proc.pid if self.proc else None,
            "restarts": self._restart_count,
        }
        if self._last_health:
            h["services"] = self._last_health.get("services", {})
        return h

    def _spawn(self) -> None:
        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-m", "data.ingestion.realtime.supervisor"],
                cwd=str(_REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            logger.info("realtime supervisor started (pid=%s)", self.proc.pid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not start realtime supervisor: %r", exc)
            self.proc = None

    def _kill_proc(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def _watch_loop(self) -> None:
        while not self._stop.is_set():
            if self.proc is None:
                self._stop.wait(5.0)
                continue

            line = b""
            with contextlib.suppress(Exception):
                line = self.proc.stdout.readline()  # type: ignore[union-attr]

            if line:
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded.startswith("HEALTH:"):
                    try:
                        self._last_health = json.loads(decoded[7:])
                        self._last_health_at = monotonic()
                    except json.JSONDecodeError:
                        pass
                elif decoded:
                    logger.info("[supervisor] %s", decoded)

            if self.proc.poll() is not None:
                rc = self.proc.returncode
                logger.error("realtime supervisor exited (rc=%s)", rc)

                now = monotonic()
                if now - self._last_stable_since > self._RESTART_WINDOW:
                    self._restart_count = 0
                    self._last_stable_since = now

                if self._restart_count >= self._MAX_RESTARTS:
                    logger.error(
                        "supervisor crashed %d times — giving up (manual restart required)",
                        self._restart_count,
                    )
                    return

                backoff = min(2**self._restart_count, 60)
                self._restart_count += 1
                logger.info(
                    "restarting supervisor in %ds (attempt #%d)", backoff, self._restart_count
                )
                if self._stop.wait(backoff):
                    return
                self._spawn()


_watchdog = _SupervisorWatchdog()


async def _fetch_celebrity_holdings():
    """Run all three celebrity holdings ingestion tasks."""
    db_url = settings.DATABASE_URL
    loaders = [
        ("congress", "data.celebrity.congress"),
        ("ark", "data.celebrity.ark"),
        ("13f", "data.celebrity.sec_13f"),
    ]
    for name, module_path in loaders:
        try:
            mod = __import__(module_path, fromlist=["run_loader"])
            if name == "13f":
                from data.celebrity.sec_13f import LoaderSettings

                ua = LoaderSettings().SEC_USER_AGENT
                count = await mod.run_loader(db_url, ua)
            else:
                count = await mod.run_loader(db_url)
            logger.info("celebrity/%s: upserted %d rows", name, count)
        except Exception:
            logger.warning("celebrity/%s: fetch failed", name, exc_info=True)


def _run_celebrity_scheduler(stop_event: threading.Event):
    """Background thread: fetch once now, then daily at 19:00 ET."""
    import zoneinfo

    et = zoneinfo.ZoneInfo("America/New_York")

    # Fetch immediately on startup
    logger.info("celebrity holdings: initial fetch on startup")
    try:
        asyncio.run(_fetch_celebrity_holdings())
    except Exception:
        logger.warning("celebrity holdings: startup fetch failed", exc_info=True)

    # Then loop: sleep until next 19:00 ET, fetch, repeat
    while not stop_event.is_set():
        from datetime import datetime, timedelta

        now_et = datetime.now(et)
        target = now_et.replace(hour=19, minute=0, second=0, microsecond=0)
        if target <= now_et:
            target += timedelta(days=1)
        # Skip weekends
        while target.weekday() >= 5:
            target += timedelta(days=1)

        wait_secs = (target - now_et).total_seconds()
        logger.info(
            "celebrity holdings: next fetch at %s ET (%.0fh)",
            target.strftime("%Y-%m-%d %H:%M"),
            wait_secs / 3600,
        )

        if stop_event.wait(timeout=wait_secs):
            break

        logger.info("celebrity holdings: daily fetch starting")
        try:
            asyncio.run(_fetch_celebrity_holdings())
        except Exception:
            logger.warning("celebrity holdings: daily fetch failed", exc_info=True)


_celeb_stop = threading.Event()
_earnings_stop = threading.Event()
_mcap_stop = threading.Event()


def _run_marketcap_scheduler(stop_event: threading.Event):
    """Background thread: refresh market_cap on startup, then daily at 06:00 ET."""
    import zoneinfo

    et = zoneinfo.ZoneInfo("America/New_York")

    logger.info("market_cap: initial fetch on startup")
    try:
        from data.ingestion.massive_marketcap import run as _mcap_run

        asyncio.run(_mcap_run())
    except Exception:
        logger.warning("market_cap: startup fetch failed", exc_info=True)

    while not stop_event.is_set():
        from datetime import datetime, timedelta

        now_et = datetime.now(et)
        target = now_et.replace(hour=6, minute=0, second=0, microsecond=0)
        if target <= now_et:
            target += timedelta(days=1)
        while target.weekday() >= 5:
            target += timedelta(days=1)

        wait_secs = (target - now_et).total_seconds()
        logger.info(
            "market_cap: next fetch at %s ET (%.0fh)",
            target.strftime("%Y-%m-%d %H:%M"),
            wait_secs / 3600,
        )

        if stop_event.wait(timeout=wait_secs):
            break

        logger.info("market_cap: daily fetch starting")
        try:
            from data.ingestion.massive_marketcap import run as _mcap_run

            asyncio.run(_mcap_run())
        except Exception:
            logger.warning("market_cap: daily fetch failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_startup_checks()
    _watchdog.start()
    app.state.watchdog = _watchdog

    from app.api.routes.admin.logs import init_log_buffer

    init_log_buffer()

    _celeb_stop.clear()
    celeb_thread = threading.Thread(
        target=_run_celebrity_scheduler,
        args=(_celeb_stop,),
        daemon=True,
        name="celeb-fetch",
    )
    celeb_thread.start()

    _mcap_stop.clear()
    mcap_thread = threading.Thread(
        target=_run_marketcap_scheduler,
        args=(_mcap_stop,),
        daemon=True,
        name="mcap-fetch",
    )
    mcap_thread.start()

    # Earnings: startup fetch + 2× daily (08:00 / 18:00 ET weekdays)
    earnings_thread = None
    try:
        from data.earnings.scheduler import run_scheduler as _run_earnings

        _earnings_stop.clear()
        earnings_thread = threading.Thread(
            target=_run_earnings,
            args=(_earnings_stop, settings.DATABASE_URL),
            daemon=True,
            name="earnings-sched",
        )
        earnings_thread.start()
    except ImportError:
        logger.warning("data.earnings not available — earnings scheduler disabled")

    try:
        yield
    finally:
        _earnings_stop.set()
        if earnings_thread is not None:
            earnings_thread.join(timeout=5)
        _mcap_stop.set()
        mcap_thread.join(timeout=5)
        _celeb_stop.set()
        celeb_thread.join(timeout=5)
        _watchdog.stop()


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
app.include_router(
    celebrity_holdings.router,
    prefix="/api/celebrity-holdings",
    tags=["celebrity-holdings"],
)
app.include_router(news.router, prefix="/api/news", tags=["news"])
app.include_router(fomc.router, prefix="/api/fomc", tags=["fomc"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/health")
async def health():
    sv = _watchdog.health
    sv_ok = sv.get("supervisor") in ("running", "disabled")

    report = get_startup_report()
    data_readiness = {}
    if report:
        for check in report.checks:
            data_readiness[check.name] = {
                "status": check.status.value,
                "message": check.message,
                **({"detail": check.detail} if check.detail else {}),
            }

    overall = "ok"
    if report and report.overall_status != "ok":
        overall = report.overall_status
    elif not sv_ok:
        overall = "degraded"

    return {
        "status": overall,
        "version": "0.1.0",
        "realtime": sv,
        "data_readiness": data_readiness,
        "startup": {
            "completed_at": (
                report.completed_at.isoformat() if report and report.completed_at else None
            ),
            "overall": report.overall_status if report else "unknown",
        },
    }
