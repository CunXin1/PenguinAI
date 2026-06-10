"""
Startup self-healing checks for PenguinAI backend.

Runs during FastAPI lifespan before any request is served.
BLOCKING checks must pass or the server refuses to start.
NON-BLOCKING checks log warnings and continue in degraded mode.
"""

import enum
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import text

logger = logging.getLogger("app.startup")


class CheckStatus(enum.StrEnum):
    OK = "ok"
    HEALED = "healed"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class CheckResult:
    name: str
    blocking: bool
    status: CheckStatus
    message: str
    healed: bool = False
    duration_ms: float = 0.0
    detail: dict | None = None


@dataclass
class StartupReport:
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    checks: list[CheckResult] = field(default_factory=list)
    overall_status: str = "unknown"

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)

    def finalize(self) -> None:
        self.completed_at = datetime.now(UTC)
        statuses = [c.status for c in self.checks]
        if any(c.status == CheckStatus.FAILED and c.blocking for c in self.checks):
            self.overall_status = "failed"
        elif CheckStatus.FAILED in statuses or CheckStatus.DEGRADED in statuses:
            self.overall_status = "degraded"
        else:
            self.overall_status = "ok"

    def to_dict(self) -> dict:
        return {
            "status": self.overall_status,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "checks": [
                {
                    "name": c.name,
                    "blocking": c.blocking,
                    "status": c.status.value,
                    "message": c.message,
                    "healed": c.healed,
                    "duration_ms": round(c.duration_ms, 1),
                    **({"detail": c.detail} if c.detail else {}),
                }
                for c in self.checks
            ],
        }


_report: StartupReport | None = None


def get_startup_report() -> StartupReport | None:
    return _report


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

_CRITICAL_TABLES = [
    "tickers",
    "signal_cache",
    "instruments",
    "bars_30m",
    "market_data_1min",
    "users",
    "earnings",
    "celebrity_holdings",
]


async def check_db_connection() -> CheckResult:
    t0 = time.monotonic()
    try:
        from app.core.database import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return CheckResult(
            name="db_connection",
            blocking=True,
            status=CheckStatus.OK,
            message="PostgreSQL connected",
            duration_ms=(time.monotonic() - t0) * 1000,
        )
    except Exception as exc:
        return CheckResult(
            name="db_connection",
            blocking=True,
            status=CheckStatus.FAILED,
            message=f"Cannot connect to PostgreSQL: {exc}",
            duration_ms=(time.monotonic() - t0) * 1000,
        )


async def check_schema_exists() -> CheckResult:
    t0 = time.monotonic()
    try:
        from app.core.database import engine

        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            existing = {row[0] for row in result}
            result = await conn.execute(
                text("SELECT viewname FROM pg_views WHERE schemaname = 'public'")
            )
            existing.update(row[0] for row in result)
            # TimescaleDB continuous aggregates appear in timescaledb_information
            try:
                result = await conn.execute(
                    text("SELECT view_name FROM timescaledb_information.continuous_aggregates")
                )
                existing.update(row[0] for row in result)
            except Exception:
                pass

        missing = [t for t in _CRITICAL_TABLES if t not in existing]
        if missing:
            return CheckResult(
                name="schema",
                blocking=True,
                status=CheckStatus.FAILED,
                message=(f"Missing tables: {missing}. Run 'make db-init' to apply db/schema/*.sql"),
                duration_ms=(time.monotonic() - t0) * 1000,
                detail={"missing": missing, "existing_count": len(existing)},
            )
        return CheckResult(
            name="schema",
            blocking=True,
            status=CheckStatus.OK,
            message=f"All {len(_CRITICAL_TABLES)} critical tables present",
            duration_ms=(time.monotonic() - t0) * 1000,
        )
    except Exception as exc:
        return CheckResult(
            name="schema",
            blocking=True,
            status=CheckStatus.FAILED,
            message=f"Schema check error: {exc}",
            duration_ms=(time.monotonic() - t0) * 1000,
        )


async def check_and_heal_tickers() -> CheckResult:
    t0 = time.monotonic()
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT count(*) FROM tickers"))
            count = result.scalar_one()

        if count > 0:
            return CheckResult(
                name="tickers",
                blocking=True,
                status=CheckStatus.OK,
                message=f"tickers: {count} rows",
                duration_ms=(time.monotonic() - t0) * 1000,
                detail={"count": count},
            )

        from scripts.bootstrap_universe import TICKER_UNIVERSE

        logger.warning("tickers table empty — bootstrapping %d core tickers", len(TICKER_UNIVERSE))
        async with AsyncSessionLocal() as db:
            for t in TICKER_UNIVERSE:
                await db.execute(
                    text("""
                        INSERT INTO tickers (ticker, name, sector, exchange, tags)
                        VALUES (:ticker, :name, :sector, :exchange, :tags)
                        ON CONFLICT (ticker) DO UPDATE SET
                            name = EXCLUDED.name, sector = EXCLUDED.sector, tags = EXCLUDED.tags
                    """),
                    {**t, "tags": t["tags"]},
                )
            await db.commit()

        return CheckResult(
            name="tickers",
            blocking=True,
            status=CheckStatus.HEALED,
            message=f"Bootstrapped {len(TICKER_UNIVERSE)} tickers into empty table",
            healed=True,
            duration_ms=(time.monotonic() - t0) * 1000,
            detail={"bootstrapped": len(TICKER_UNIVERSE)},
        )
    except Exception as exc:
        return CheckResult(
            name="tickers",
            blocking=True,
            status=CheckStatus.FAILED,
            message=f"Ticker check/heal failed: {exc}",
            duration_ms=(time.monotonic() - t0) * 1000,
        )


async def check_redis() -> CheckResult:
    t0 = time.monotonic()
    try:
        from redis.asyncio import Redis

        from app.core.config import settings

        conn = Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        try:
            await conn.ping()
            return CheckResult(
                name="redis",
                blocking=False,
                status=CheckStatus.OK,
                message="Redis connected",
                duration_ms=(time.monotonic() - t0) * 1000,
            )
        finally:
            await conn.aclose()
    except Exception as exc:
        return CheckResult(
            name="redis",
            blocking=False,
            status=CheckStatus.DEGRADED,
            message=f"Redis unavailable (rate limiting + Celery dispatch degraded): {exc}",
            duration_ms=(time.monotonic() - t0) * 1000,
        )


async def check_and_heal_signal_cache() -> CheckResult:
    t0 = time.monotonic()
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT count(*) FROM signal_cache"))
            total = result.scalar_one()
            result = await db.execute(
                text("SELECT count(*) FROM signal_cache WHERE expires_at > now()")
            )
            fresh = result.scalar_one()

        if fresh > 0:
            return CheckResult(
                name="signal_cache",
                blocking=False,
                status=CheckStatus.OK,
                message=f"signal_cache: {fresh} fresh / {total} total",
                duration_ms=(time.monotonic() - t0) * 1000,
                detail={"total": total, "fresh": fresh},
            )

        healed = False
        heal_msg = ""
        try:
            from celery import Celery

            from app.core.config import settings

            c = Celery(broker=settings.REDIS_URL)
            try:
                c.send_task("ml.tasks.hourly_signal_cache.refresh_top100", queue="ml_inference")
                healed = True
                heal_msg = "Dispatched refresh_top100 (queued until ML worker picks it up)"
                logger.info("signal_cache stale — dispatched refresh_top100")
            finally:
                c.close()
        except Exception as exc:
            heal_msg = f"Cannot dispatch Celery refresh: {exc}"
            logger.warning(heal_msg)

        return CheckResult(
            name="signal_cache",
            blocking=False,
            status=CheckStatus.HEALED if healed else CheckStatus.DEGRADED,
            message=f"signal_cache: 0 fresh (total={total}). {heal_msg}",
            healed=healed,
            duration_ms=(time.monotonic() - t0) * 1000,
            detail={"total": total, "fresh": 0, "heal_dispatched": healed},
        )
    except Exception as exc:
        return CheckResult(
            name="signal_cache",
            blocking=False,
            status=CheckStatus.DEGRADED,
            message=f"Signal cache check failed: {exc}",
            duration_ms=(time.monotonic() - t0) * 1000,
        )


async def check_bars_data() -> CheckResult:
    t0 = time.monotonic()
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT 1 FROM bars_30m LIMIT 1"))
            has_bars = result.first() is not None
            result = await db.execute(text("SELECT count(*) FROM instruments"))
            instruments_count = result.scalar_one()

        if has_bars and instruments_count > 0:
            return CheckResult(
                name="bars_30m",
                blocking=False,
                status=CheckStatus.OK,
                message=f"bars_30m: has data, instruments: {instruments_count}",
                duration_ms=(time.monotonic() - t0) * 1000,
                detail={"bars_30m_has_data": True, "instruments": instruments_count},
            )

        parts = []
        if instruments_count == 0:
            parts.append("instruments table empty")
        if not has_bars:
            parts.append("bars_30m empty — charts and ML models will not work")
        msg = "; ".join(parts) + ". Run 'make import-30min' to load historical data."
        logger.warning("MANUAL ACTION NEEDED: %s", msg)

        return CheckResult(
            name="bars_30m",
            blocking=False,
            status=CheckStatus.DEGRADED,
            message=msg,
            duration_ms=(time.monotonic() - t0) * 1000,
            detail={"bars_30m_has_data": False, "instruments": instruments_count},
        )
    except Exception as exc:
        return CheckResult(
            name="bars_30m",
            blocking=False,
            status=CheckStatus.DEGRADED,
            message=f"Bar data check failed: {exc}",
            duration_ms=(time.monotonic() - t0) * 1000,
        )


async def check_market_data_1min() -> CheckResult:
    t0 = time.monotonic()
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT max(time) FROM market_data_1min"))
            latest = result.scalar_one()

        if latest is None:
            return CheckResult(
                name="market_data_1min",
                blocking=False,
                status=CheckStatus.DEGRADED,
                message=(
                    "market_data_1min empty — live quotes/charts unavailable "
                    "until realtime supervisor streams data"
                ),
                duration_ms=(time.monotonic() - t0) * 1000,
                detail={"count": 0},
            )

        return CheckResult(
            name="market_data_1min",
            blocking=False,
            status=CheckStatus.OK,
            message=f"market_data_1min: latest={latest.isoformat()}",
            duration_ms=(time.monotonic() - t0) * 1000,
            detail={"latest": latest.isoformat()},
        )
    except Exception as exc:
        return CheckResult(
            name="market_data_1min",
            blocking=False,
            status=CheckStatus.DEGRADED,
            message=f"market_data_1min check failed: {exc}",
            duration_ms=(time.monotonic() - t0) * 1000,
        )


async def check_and_seed_admin() -> CheckResult:
    """Ensure at least one ADMIN user exists. Create or sync from .env config."""
    t0 = time.monotonic()
    try:
        import secrets

        from app.core.config import settings
        from app.core.database import AsyncSessionLocal
        from app.core.security import hash_password, verify_password

        email = settings.ADMIN_EMAIL
        explicit_pw = settings.ADMIN_PASSWORD  # empty string if not set in .env

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("SELECT id, email, password_hash FROM users WHERE email = :email"),
                {"email": email},
            )
            existing = result.first()

        # Case 1: user exists with correct email
        if existing is not None:
            # If .env has an explicit password, make sure the hash matches
            if explicit_pw and not verify_password(explicit_pw, existing.password_hash or ""):
                pw_hash = hash_password(explicit_pw)
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        text(
                            "UPDATE users SET password_hash = :pw_hash, tier = 'ADMIN', "
                            "is_active = true, email_verified = true WHERE email = :email"
                        ),
                        {"pw_hash": pw_hash, "email": email},
                    )
                    await db.commit()
                return CheckResult(
                    name="admin_user",
                    blocking=False,
                    status=CheckStatus.HEALED,
                    message=f"ADMIN password synced from .env: {email}",
                    healed=True,
                    duration_ms=(time.monotonic() - t0) * 1000,
                )

            # Ensure tier is ADMIN even if account was previously downgraded
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text(
                        "UPDATE users SET tier = 'ADMIN', is_active = true, "
                        "email_verified = true WHERE email = :email AND tier != 'ADMIN'"
                    ),
                    {"email": email},
                )
                await db.commit()

            return CheckResult(
                name="admin_user",
                blocking=False,
                status=CheckStatus.OK,
                message=f"ADMIN user exists: {email}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # Case 2: no user with this email — create one
        password = explicit_pw or secrets.token_urlsafe(16)
        pw_hash = hash_password(password)

        async with AsyncSessionLocal() as db:
            await db.execute(
                text("""
                    INSERT INTO users (email, username, password_hash, display_name, tier, is_active, email_verified)
                    VALUES (:email, 'admin', :pw_hash, 'Admin', 'ADMIN', true, true)
                """),
                {"email": email, "pw_hash": pw_hash},
            )
            await db.commit()

        logger.warning("=" * 60)
        logger.warning("ADMIN account created:")
        logger.warning("  Email:    %s", email)
        logger.warning("  Password: %s", password)
        logger.warning("  *** Change this password immediately! ***")
        logger.warning("=" * 60)

        return CheckResult(
            name="admin_user",
            blocking=False,
            status=CheckStatus.HEALED,
            message=f"Created ADMIN user: {email}",
            healed=True,
            duration_ms=(time.monotonic() - t0) * 1000,
        )
    except Exception as exc:
        return CheckResult(
            name="admin_user",
            blocking=False,
            status=CheckStatus.DEGRADED,
            message=f"Admin seed failed: {exc}",
            duration_ms=(time.monotonic() - t0) * 1000,
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

_STATUS_ICON = {"ok": "+", "healed": "~", "degraded": "!", "failed": "X"}


async def run_startup_checks() -> StartupReport:
    global _report  # noqa: PLW0603

    from app.core.config import settings

    if settings.DATABASE_URL.startswith("sqlite"):
        report = StartupReport()
        report.finalize()
        _report = report
        return report

    report = StartupReport()
    logger.info("=" * 60)
    logger.info("PenguinAI startup self-healing checks")
    logger.info("=" * 60)

    blocking = [check_db_connection, check_schema_exists, check_and_heal_tickers]
    for fn in blocking:
        result = await fn()
        report.add(result)
        _log(result)
        if result.status == CheckStatus.FAILED:
            logger.critical("BLOCKING check '%s' FAILED — %s", result.name, result.message)
            report.finalize()
            _report = report
            raise RuntimeError(f"Startup check '{result.name}' failed: {result.message}")

    non_blocking = [
        check_redis,
        check_and_seed_admin,
        check_and_heal_signal_cache,
        check_bars_data,
        check_market_data_1min,
    ]
    for fn in non_blocking:
        result = await fn()
        report.add(result)
        _log(result)

    report.finalize()
    _report = report

    elapsed = (
        (report.completed_at - report.started_at).total_seconds() * 1000
        if report.completed_at
        else 0
    )
    logger.info("-" * 60)
    logger.info("Startup checks: %s (%.0fms)", report.overall_status.upper(), elapsed)
    for c in report.checks:
        logger.info("  [%s] %-20s %s", _STATUS_ICON.get(c.status.value, "?"), c.name, c.message)
    logger.info("-" * 60)
    return report


def _log(result: CheckResult) -> None:
    lvl = {
        CheckStatus.OK: logging.INFO,
        CheckStatus.HEALED: logging.WARNING,
        CheckStatus.DEGRADED: logging.WARNING,
        CheckStatus.FAILED: logging.ERROR,
    }[result.status]
    logger.log(
        lvl,
        "[%-8s] %s: %s (%.0fms)",
        result.status.value.upper(),
        result.name,
        result.message,
        result.duration_ms,
    )
