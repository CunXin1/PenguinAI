from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tier
from app.core.database import engine
from app.core.utils import human_size

router = APIRouter()
AdminUser = Depends(require_tier("ADMIN"))


# Tables we care about + their timestamp column (if any) for freshness
_TRACKED_TABLES: list[tuple[str, str | None]] = [
    ("bars_30m", "ts"),
    ("bars_1d", "ts"),
    ("market_data_1min", "time"),
    ("signal_cache", "computed_at"),
    ("social_posts", "time"),
    ("users", "created_at"),
    ("tickers", None),
    ("instruments", None),
    ("celebrity_holdings", "trade_date"),
    ("earnings", "report_date"),
    ("news_articles", "time"),
    ("symbol_requests", "created_at"),
]


@router.get("/health")
async def db_health(
    db: Annotated[AsyncSession, Depends(get_db)],
    _=AdminUser,
):
    """Connection pool stats, table sizes, row counts, freshness."""
    # Connection pool introspection
    pool = engine.pool
    pool_info = {
        "pool_size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "max_overflow": engine.pool._max_overflow,
    }

    # Active connections from pg_stat_activity
    result = await db.execute(
        text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
    )
    active_connections = result.scalar() or 0

    # Table sizes using pg_stat (O(1), no full table scan)
    result = await db.execute(
        text("""
            SELECT
                s.relname AS table_name,
                s.n_live_tup AS approx_rows,
                pg_total_relation_size(c.oid) AS total_bytes
            FROM pg_class c
            JOIN pg_stat_user_tables s ON c.relname = s.relname
            WHERE s.schemaname = 'public'
            ORDER BY pg_total_relation_size(c.oid) DESC
        """)
    )
    all_tables = {row.table_name: row for row in result.mappings().all()}

    tables = []
    for table_name, ts_col in _TRACKED_TABLES:
        row = all_tables.get(table_name)
        if row is None:
            continue

        latest_ts = None
        if ts_col:
            try:
                ts_result = await db.execute(
                    text(f"SELECT max({ts_col}) FROM {table_name}")  # noqa: S608
                )
                latest_ts = ts_result.scalar()
            except Exception:
                pass

        size_bytes = int(row["total_bytes"] or 0)
        tables.append(
            {
                "name": table_name,
                "approx_rows": int(row["approx_rows"] or 0),
                "size_bytes": size_bytes,
                "size_human": human_size(size_bytes),
                "latest_ts": latest_ts.isoformat() if latest_ts else None,
            }
        )

    # Total DB size
    result = await db.execute(text("SELECT pg_database_size(current_database())"))
    total_bytes = result.scalar() or 0

    return {
        "connection_pool": pool_info,
        "active_connections": active_connections,
        "tables": tables,
        "total_db_size_bytes": total_bytes,
        "total_db_size_human": human_size(total_bytes),
    }
