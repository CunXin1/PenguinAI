"""One-time backfill: round already-stored price/indicator values in the DB to the
per-category precision defined in compute_indicators.ROUND_DECIMALS (prices + ratios
-> 4 dp, rsi_14 -> 2 dp, obv -> 0 dp).

This brings existing rows in line with the rounding now applied at compute/ingest time
(compute_indicators.py, data/ingestion/realtime/indicators.py, the Massive loaders).
It does NOT change column types or save storage (DOUBLE PRECISION is fixed 8 bytes) —
it only standardizes the stored decimals.

Targets DOUBLE PRECISION columns only. NUMERIC(p,s) columns (e.g. market_data_1min's
OHLC) already enforce their scale, so they are skipped automatically (no matching
double columns). Idempotent: re-running is a no-op (rows already at target precision are
not rewritten). Chunked per instrument/ticker so a 200M+ row hypertable stays manageable.

Usage (defaults target the penguinai docker DB; override via PG* env vars):
    python backend/scripts/market_data/round_existing_precision.py            # all tables
    python backend/scripts/market_data/round_existing_precision.py --dry-run  # count only
    python backend/scripts/market_data/round_existing_precision.py --table bars_1d
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# same-dir import: ROUND_DECIMALS is the single source of truth for the precision policy
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compute_indicators import ROUND_DECIMALS  # noqa: E402

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover
    psycopg = None

DEFAULT_TABLES = ("bars_30m", "bars_1d", "market_data_1min")


def _connect() -> psycopg.Connection:
    if psycopg is None:
        raise RuntimeError("psycopg is required. Run inside the loader env / container.")
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "penguinai"),
        user=os.getenv("PGUSER", "penguinai"),
        password=os.getenv("PGPASSWORD", "penguinai_dev"),
    )


def _double_round_cols(conn: psycopg.Connection, table: str) -> dict[str, int]:
    """ROUND_DECIMALS columns that exist on `table` as DOUBLE PRECISION (the only ones
    where rounding the stored value changes anything)."""
    rows = conn.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %s AND data_type = 'double precision'
        """,
        (table,),
    ).fetchall()
    present = {r[0] for r in rows}
    return {c: n for c, n in ROUND_DECIMALS.items() if c in present}


def _chunk_column(conn: psycopg.Connection, table: str) -> str | None:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    ).fetchall()
    cols = {r[0] for r in rows}
    for cand in ("instrument_id", "ticker"):
        if cand in cols:
            return cand
    return None


def _round_table(conn: psycopg.Connection, table: str, *, dry_run: bool) -> None:
    cols = _double_round_cols(conn, table)
    if not cols:
        print(f"  {table}: no DOUBLE PRECISION rounding columns — skipped")
        return
    chunk_col = _chunk_column(conn, table)
    if chunk_col is None:
        print(f"  {table}: no instrument_id/ticker chunk column — skipped")
        return

    # round(col::numeric, n) is the only valid cast (PG has no round(double, int)).
    set_clause = ", ".join(f"{c} = round({c}::numeric, {n})" for c, n in cols.items())
    # only rewrite rows where at least one column isn't already at target precision
    changed = " OR ".join(
        f"{c} IS DISTINCT FROM round({c}::numeric, {n})" for c, n in cols.items()
    )

    keys = [r[0] for r in conn.execute(
        f"SELECT DISTINCT {chunk_col} FROM {table} ORDER BY {chunk_col}"
    ).fetchall()]
    print(
        f"  {table}: {len(cols)} cols, {len(keys):,} {chunk_col} groups"
        f"{' (dry-run)' if dry_run else ''}"
    )

    started = time.time()
    total = 0
    for i, key in enumerate(keys, start=1):
        if dry_run:
            n = conn.execute(
                f"SELECT count(*) FROM {table} WHERE {chunk_col} = %s AND ({changed})",
                (key,),
            ).fetchone()[0]
            total += n
        else:
            cur = conn.execute(
                f"UPDATE {table} SET {set_clause} WHERE {chunk_col} = %s AND ({changed})",
                (key,),
            )
            total += cur.rowcount
            conn.commit()
        if i % 250 == 0 or i == len(keys):
            print(
                f"    {i:,}/{len(keys):,} groups  rows={'to change' if dry_run else 'updated'}="
                f"{total:,}  elapsed={time.time() - started:,.0f}s",
                file=sys.stderr, flush=True,
            )
    verb = "would round" if dry_run else "rounded"
    print(f"  {table}: {verb} {total:,} rows")


def _vacuum(table: str) -> None:
    conn = _connect()
    conn.autocommit = True  # VACUUM cannot run inside a transaction block
    try:
        conn.execute(f"VACUUM (ANALYZE) {table}")
    finally:
        conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--table", action="append", help="Limit to these tables (repeatable).")
    p.add_argument("--dry-run", action="store_true", help="Count rows to change, write nothing.")
    p.add_argument("--no-vacuum", action="store_true", help="Skip VACUUM ANALYZE after rounding.")
    args = p.parse_args()

    tables = args.table or list(DEFAULT_TABLES)
    print(f"rounding existing precision in: {', '.join(tables)}")
    conn = _connect()
    try:
        for t in tables:
            _round_table(conn, t, dry_run=args.dry_run)
    finally:
        conn.close()

    if not args.dry_run and not args.no_vacuum:
        for t in tables:
            print(f"  VACUUM ANALYZE {t} ...")
            _vacuum(t)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
