"""
Shared test infrastructure for all backend/app tests.

Uses SQLite+aiosqlite as an in-memory test database.  PostgreSQL-specific
column types (UUID, ARRAY, TIMESTAMP(timezone=True)) are patched at the
DDL/compilation level so SQLAlchemy can create identical tables in SQLite.

IMPORTANT: environment overrides MUST happen before any app module is imported
because ``app.core.database`` eagerly creates the async engine at module scope.
"""

import json as _json
import os
import sqlite3
import uuid as _uuid_mod

# ── 1. Override DATABASE_URL *before* any app import ────────────────────────
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest"
os.environ["ALLOWED_ORIGINS"] = '["http://localhost:3000"]'

# Register SQLite adapters for types that PostgreSQL handles natively.
sqlite3.register_adapter(_uuid_mod.UUID, lambda u: str(u))
sqlite3.register_adapter(list, lambda lst: _json.dumps(lst))
sqlite3.register_converter("CHAR", lambda b: b.decode())

# Clear the lru_cache on get_settings so the test DATABASE_URL is picked up.
from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

# ── Now safe to import the rest of the application ──────────────────────────
import uuid  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import DateTime, String, Text, TypeDecorator, event  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.signal_cache import SignalCache  # noqa: E402
from app.models.ticker import Ticker  # noqa: E402
from app.models.user import User  # noqa: E402

# ---------------------------------------------------------------------------
# SQLite-compatible test engine
# ---------------------------------------------------------------------------
# Re-use the same URL that database.py now resolves (sqlite+aiosqlite://)
# but create our own engine with pool settings appropriate for tests.

_test_engine = create_async_engine(
    "sqlite+aiosqlite://",
    echo=False,
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
_TestSessionLocal = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)


# ---------------------------------------------------------------------------
# Patch PostgreSQL-specific column types so SQLite DDL works
# ---------------------------------------------------------------------------

class _JSONList(TypeDecorator):
    """Store Python lists as JSON text in SQLite (replaces PG ARRAY)."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return "[]"
        return _json.dumps(value)

    def process_result_value(self, value, dialect):
        if not value:
            return []
        return _json.loads(value)


class _TZDateTime(TypeDecorator):
    """Ensure datetimes read from SQLite are UTC-aware (PG does this natively)."""
    impl = DateTime
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def _patch_pg_types_for_sqlite() -> None:
    """Rewrite PG-only column types in-place on the mapped Table metadata so
    that ``Base.metadata.create_all`` emits valid SQLite DDL.
    """
    from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    for table in Base.metadata.tables.values():
        for col in table.columns:
            col_type = col.type

            if isinstance(col_type, PG_UUID):
                col.type = String(36)

            if isinstance(col_type, PG_ARRAY):
                col.type = _JSONList()

            if isinstance(col_type, DateTime) and getattr(col_type, "timezone", False):
                col.type = _TZDateTime()


_pg_types_patched = False


async def _create_tables() -> None:
    global _pg_types_patched  # noqa: PLW0603
    if not _pg_types_patched:
        _patch_pg_types_for_sqlite()
        _pg_types_patched = True

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _drop_tables() -> None:
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Override FastAPI dependency
# ---------------------------------------------------------------------------

async def _override_get_db():
    async with _TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = _override_get_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def _setup_teardown_tables():
    """Create all tables before each test and drop them after."""
    await _create_tables()
    yield
    await _drop_tables()


@pytest.fixture
async def db_session() -> AsyncSession:
    """Raw AsyncSession for direct DB setup / assertions."""
    async with _TestSessionLocal() as session:
        yield session


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="free@example.com",
        password_hash=hash_password("Test1234!"),
        display_name="Free User",
        tier="FREE",
        is_active=True,
        email_verified=False,
        token_version=0,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def pro_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="pro@example.com",
        password_hash=hash_password("Test1234!"),
        display_name="Pro User",
        tier="PRO",
        is_active=True,
        email_verified=False,
        token_version=0,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        password_hash=hash_password("Test1234!"),
        display_name="Admin User",
        tier="ADMIN",
        is_active=True,
        email_verified=True,
        token_version=0,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers():
    """Returns a callable: auth_headers(user) -> {"Authorization": "Bearer <token>"}"""

    def _make(user: User) -> dict[str, str]:
        token = create_access_token(str(user.id), getattr(user, "token_version", 0))
        return {"Authorization": f"Bearer {token}"}

    return _make


@pytest.fixture
async def test_ticker(db_session: AsyncSession) -> Ticker:
    ticker = Ticker(
        ticker="AAPL",
        name="Apple Inc.",
        exchange="NASDAQ",
        sector="Technology",
        industry="Consumer Electronics",
        market_cap=3_000_000_000_000,
        tags=[],
        is_active=True,
    )
    db_session.add(ticker)
    await db_session.commit()
    await db_session.refresh(ticker)
    return ticker


@pytest.fixture
async def test_signal(db_session: AsyncSession, test_ticker: Ticker) -> SignalCache:
    now = datetime.now(UTC)
    signal = SignalCache(
        ticker="AAPL",
        direction="LONG",
        confidence=Decimal("0.8500"),
        holding_period="SHORT_TERM",
        xgb_prob_up=Decimal("0.8200"),
        rf_prob_up=Decimal("0.7800"),
        ensemble_prob=Decimal("0.8000"),
        finbert_score=Decimal("0.6500"),
        post_count=42,
        hawk_dove_ref=Decimal("0.1000"),
        ai_attribution="Strong momentum + positive sentiment",
        ai_analysis="Apple showing bullish technical setup with rising volume",
        tier_required="FREE",
        computed_at=now,
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(signal)
    await db_session.commit()
    await db_session.refresh(signal)
    return signal
