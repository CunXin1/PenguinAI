import asyncio
import atexit
import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

# data/, ml/, scripts/ live at the repo root — this MUST run before importing any
# route module (e.g. fomc → data.fomc.meetings), or that import fails in the
# container, where the app runs from backend/ and the repo root isn't on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.api.routes import (  # noqa: E402  (depends on the sys.path setup above)
    admin,
    auth,
    celebrity_holdings,
    chat,
    earnings,
    fear_greed,
    fomc,
    market_data,
    news,
    pinned_signals,
    signals,
    symbols,
    tickers,
    watchlist,
)
from app.core.config import settings  # noqa: E402
from app.core.startup import get_startup_report, run_startup_checks  # noqa: E402

logger = logging.getLogger("app.realtime")


class _ProcessWatchdog:
    """Generic subprocess watchdog: auto-restarts on crash, captures stdout."""

    _MAX_RESTARTS = 10
    _RESTART_WINDOW = 3600.0

    def __init__(self, name: str, cmd: list[str], *, cwd: str | Path | None = None,
                 enabled: bool = True, parse_health: bool = False):
        self.name = name
        self.cmd = cmd
        self.cwd = str(cwd) if cwd else None
        self.proc: subprocess.Popen | None = None
        self.enabled = enabled
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._restart_count = 0
        self._last_stable_since = monotonic()
        self._last_health: dict | None = None
        self._parse_health = parse_health

    def start(self) -> None:
        if not self.enabled:
            logger.info("%s: disabled", self.name)
            return
        self._spawn()
        if self.proc is not None:
            self._thread = threading.Thread(
                target=self._watch_loop, daemon=True, name=f"wd-{self.name}"
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kill_proc()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        return {
            "status": "running" if self.alive else "dead",
            "pid": self.proc.pid if self.proc else None,
            "restarts": self._restart_count,
            **({"services": self._last_health.get("services", {})} if self._last_health else {}),
        }

    def _spawn(self) -> None:
        try:
            self.proc = subprocess.Popen(
                self.cmd, cwd=self.cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=False,
            )
            logger.info("%s started (pid=%s)", self.name, self.proc.pid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not start %s: %r", self.name, exc)
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
                if self._parse_health and decoded.startswith("HEALTH:"):
                    with contextlib.suppress(json.JSONDecodeError):
                        self._last_health = json.loads(decoded[7:])
                elif decoded:
                    logger.info("[%s] %s", self.name, decoded)

            if self.proc.poll() is not None:
                rc = self.proc.returncode
                logger.error("%s exited (rc=%s)", self.name, rc)

                now = monotonic()
                if now - self._last_stable_since > self._RESTART_WINDOW:
                    self._restart_count = 0
                    self._last_stable_since = now

                if self._restart_count >= self._MAX_RESTARTS:
                    logger.error(
                        "%s crashed %d times — giving up", self.name, self._restart_count
                    )
                    return

                backoff = min(2**self._restart_count, 60)
                self._restart_count += 1
                logger.info(
                    "restarting %s in %ds (attempt #%d)",
                    self.name, backoff, self._restart_count,
                )
                if self._stop.wait(backoff):
                    return
                self._spawn()


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

_celery_enabled = os.getenv("CELERY_EMBEDDED", "true").strip().lower() not in (
    "0", "false", "no", "off",
)
_celery_worker = _ProcessWatchdog(
    "celery-worker",
    [sys.executable, "-m", "celery", "-A", "ml.tasks.celery_app",
     "worker", "--queues=ml_inference,default", "-c", "2", "--loglevel=info"],
    cwd=_REPO_ROOT,
    enabled=_celery_enabled,
)
_celery_beat = _ProcessWatchdog(
    "celery-beat",
    [sys.executable, "-m", "celery", "-A", "ml.tasks.celery_app",
     "beat", "--loglevel=info"],
    cwd=_REPO_ROOT,
    enabled=_celery_enabled,
)


_all_watchdogs: list[_ProcessWatchdog] = [_celery_worker, _celery_beat]


def _cleanup_subprocesses():
    """Kill all managed subprocesses — safety net for uvicorn --reload."""
    for wd in _all_watchdogs:
        wd._kill_proc()
    _watchdog._kill_proc()


atexit.register(_cleanup_subprocesses)


def _sigterm_handler(signum, frame):
    _cleanup_subprocesses()
    sys.exit(0)


signal.signal(signal.SIGTERM, _sigterm_handler)


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
_news_stop = threading.Event()
_seed_stop = threading.Event()
_fomc_stop = threading.Event()
_fng_stop = threading.Event()
_freshness_stop = threading.Event()


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

    _celery_worker.start()
    _celery_beat.start()
    app.state.celery_worker = _celery_worker
    app.state.celery_beat = _celery_beat

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

    # News: startup fetch + tiered periodic (tier-1 every 15 min, tier-2 every 60 min)
    news_thread = None
    try:
        from data.news.scheduler import run_scheduler as _run_news

        _news_stop.clear()
        news_thread = threading.Thread(
            target=_run_news,
            args=(_news_stop, settings.DATABASE_URL, news.invalidate_news_cache),
            daemon=True,
            name="news-sched",
        )
        news_thread.start()
    except ImportError:
        logger.warning("data.news not available — news scheduler disabled")

    # FOMC: startup fetch + statements daily + news/FedWatch every 30 min
    fomc_thread = None
    try:
        from data.fomc.scheduler import run_scheduler as _run_fomc

        _fomc_stop.clear()
        fomc_thread = threading.Thread(
            target=_run_fomc,
            args=(_fomc_stop, settings.DATABASE_URL),
            daemon=True,
            name="fomc-sched",
        )
        fomc_thread.start()
    except ImportError:
        logger.warning("data.fomc.scheduler not available — FOMC scheduler disabled")

    # Fear & Greed + VIX/VVIX: startup fetch + session-aware refresh (8 min during
    # the regular session; 15 min pre/after; 60 min off-session). The scheduler
    # publishes its health into app.state.fng_health for the admin data-source panel.
    fng_thread = None
    app.state.fng_health = {}
    try:
        from app.core.market_clock import get_session_phase
        from data.fear_greed.scheduler import run_scheduler as _run_fng

        _fng_stop.clear()
        fng_thread = threading.Thread(
            target=_run_fng,
            args=(_fng_stop, settings.DATABASE_URL),
            kwargs={"health": app.state.fng_health, "phase_fn": get_session_phase},
            daemon=True,
            name="fng-sched",
        )
        fng_thread.start()
    except ImportError:
        logger.warning("data.fear_greed.scheduler not available — Fear&Greed scheduler disabled")

    # Seed critical market data if bars_30m is empty (checks DB → parquets → Massive API)
    seed_thread = None
    try:
        from app.core.seed_market_data import run_seed_thread

        _seed_stop.clear()
        seed_thread = threading.Thread(
            target=run_seed_thread,
            args=(_seed_stop,),
            daemon=True,
            name="seed-data",
        )
        seed_thread.start()
    except ImportError:
        logger.warning("seed_market_data not available — market data seed disabled")

    # Data freshness: roll the 1-min stream forward into bars_30m / bars_1d on startup
    # + daily after close, so the 30-min/daily stores never drift stale between imports.
    freshness_thread = None
    try:
        from app.core.freshness import run_freshness_scheduler

        _freshness_stop.clear()
        freshness_thread = threading.Thread(
            target=run_freshness_scheduler,
            args=(_freshness_stop,),
            daemon=True,
            name="freshness-sched",
        )
        freshness_thread.start()
    except ImportError:
        logger.warning("app.core.freshness not available — freshness backfill disabled")

    try:
        yield
    finally:
        _freshness_stop.set()
        if freshness_thread is not None:
            freshness_thread.join(timeout=5)
        _seed_stop.set()
        if seed_thread is not None:
            seed_thread.join(timeout=5)
        _fng_stop.set()
        if fng_thread is not None:
            fng_thread.join(timeout=5)
        _fomc_stop.set()
        if fomc_thread is not None:
            fomc_thread.join(timeout=5)
        _news_stop.set()
        if news_thread is not None:
            news_thread.join(timeout=5)
        _earnings_stop.set()
        if earnings_thread is not None:
            earnings_thread.join(timeout=5)
        _mcap_stop.set()
        mcap_thread.join(timeout=5)
        _celeb_stop.set()
        celeb_thread.join(timeout=5)
        _celery_beat.stop()
        _celery_worker.stop()
        _watchdog.stop()

        # Dispose the DB connection pool last (the steps above may still need it).
        # Prevents leaked connections on reload / redeploy.
        with contextlib.suppress(Exception):
            from app.core.database import engine

            await engine.dispose()


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


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Attach baseline security response headers to every response."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # HSTS only matters over HTTPS (browsers ignore it on plain HTTP); advertise it
    # in production where a TLS-terminating proxy sits in front.
    if not settings.DEBUG:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
        )
    return response


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
app.include_router(
    pinned_signals.router, prefix="/api/pinned-signals", tags=["pinned-signals"]
)
app.include_router(fomc.router, prefix="/api/fomc", tags=["fomc"])
app.include_router(fear_greed.router, prefix="/api/fear-greed", tags=["fear-greed"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
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

    celery_health = {
        "worker": _celery_worker.health,
        "beat": _celery_beat.health,
    }
    workers_ok = _celery_worker.health.get("status") in ("running", "disabled")
    if not workers_ok and overall == "ok":
        overall = "degraded"

    return {
        "status": overall,
        "version": "0.1.0",
        "realtime": sv,
        "celery": celery_health,
        "data_readiness": data_readiness,
        "startup": {
            "completed_at": (
                report.completed_at.isoformat() if report and report.completed_at else None
            ),
            "overall": report.overall_status if report else "unknown",
        },
    }


@app.get("/health/live")
async def health_live():
    """Liveness probe — the process is up. No dependency checks (k8s livenessProbe)."""
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready(response: Response):
    """Readiness probe — probes the DB (hard dependency) + Redis (soft). Returns 503
    when the DB is unreachable so orchestrators stop routing here (k8s readinessProbe)."""
    from sqlalchemy import text as _sql_text

    from app.core.database import engine
    from app.core.rate_limit import _get_redis

    checks: dict[str, str] = {}

    db_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(_sql_text("SELECT 1"))
        db_ok = True
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"

    try:
        redis = await _get_redis()
        if redis is None:
            checks["redis"] = "unavailable"  # rate limiting degrades gracefully
        else:
            await redis.ping()
            checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {type(exc).__name__}"

    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if db_ok else "not_ready", "checks": checks}
