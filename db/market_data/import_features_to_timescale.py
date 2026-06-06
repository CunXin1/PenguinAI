"""Load the cleaned, indicator-rich parquet into TimescaleDB (parallel, fast).

  by_symbol/<asset>/<SYMBOL>.parquet      -> bars_30m  (30-min bars + indicators)
  features_daily/<asset>/<SYMBOL>.parquet -> bars_1d   (daily bars + indicators + returns)

Speed strategy (each file is one symbol spanning 2000-2026, i.e. EVERY time chunk):
  * Drop the PRIMARY KEY and secondary indexes before loading, rebuild once at the
    end with a big maintenance_work_mem. Otherwise every COPY row maintains the PK
    btree scattered across ~320 monthly chunks -- the dominant cost.
  * COPY in parallel with N worker processes, each on its own connection.
  * Build rows with zip() (C-level) instead of a per-row generator; convert indicator
    NaN -> SQL NULL and volume floats -> int64, both vectorized in Arrow.

Run on the host against the compose DB. Apply sql/002 with --init-schema.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_common import connect, finish_run, init_schema, preload_instruments, start_run

# Windows reserved device names — mirrors export_by_symbol.safe_filename's suffixing
# (PRN -> PRN_.parquet). Inlined so the DB loader has no dependency on the data-refresh
# scripts in backend/scripts/market_data/.
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CLOCK$"} | {f"COM{i}" for i in range(10)} | {f"LPT{i}" for i in range(10)}

BARS_30M = [
    "rth", "raw_open", "raw_high", "raw_low", "raw_close", "raw_volume",
    "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
    "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "ema_50",
    "macd", "macd_signal", "macd_hist", "rsi_14",
    "bb_mid", "bb_upper", "bb_lower", "bb_pctb", "bb_bw",
    "atr_14", "obv", "vwap_day", "ret_1bar",
]
BARS_1D = [
    "rth_bars", "raw_close",
    "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
    "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "ema_50",
    "macd", "macd_signal", "macd_hist", "rsi_14",
    "bb_mid", "bb_upper", "bb_lower", "bb_pctb", "bb_bw",
    "atr_14", "obv",
    "ret_1d", "ret_5d", "ret_21d", "ret_63d", "ret_126d", "ret_252d", "gap_overnight",
]
INT_COLS = {"raw_volume", "adj_volume", "rth_bars"}

SECONDARY_INDEXES = {
    "bars_30m_instrument_ts_desc_idx": "CREATE INDEX bars_30m_instrument_ts_desc_idx ON bars_30m (instrument_id, ts DESC)",
    "bars_1d_instrument_ts_desc_idx": "CREATE INDEX bars_1d_instrument_ts_desc_idx ON bars_1d (instrument_id, ts DESC)",
}
PK_DDL = {
    "bars_30m": "ALTER TABLE bars_30m ADD CONSTRAINT bars_30m_pkey PRIMARY KEY (ts, instrument_id)",
    "bars_1d": "ALTER TABLE bars_1d ADD CONSTRAINT bars_1d_pkey PRIMARY KEY (ts, instrument_id)",
}


def stem_to_symbol(stem: str) -> str:
    """Undo safe_filename's reserved-name suffix (PRN -> PRN_)."""
    if stem.endswith("_") and stem[:-1].upper() in _RESERVED:
        return stem[:-1]
    return stem


# --------------------------------------------------------------------------- worker
_CONN = None


def _init_worker():
    global _CONN
    _CONN = connect()
    _CONN.execute("SET synchronous_commit TO off")
    _CONN.commit()


def _copy_file(task):
    path_str, table, cols, ts_col, iid, rth_only = task
    t = pq.read_table(path_str)
    # Some symbols (~32) are base-OHLC parquet without indicator/rth columns
    # (backfilled but never re-indicatored). Skip rather than crash on t.column().
    missing = [c for c in (*cols, ts_col) if c not in t.column_names]
    if missing:
        print(f"  skip {path_str}: missing {missing[:4]}", file=sys.stderr, flush=True)
        return 0
    if rth_only and "rth" in t.column_names:
        t = t.filter(pc.field("rth"))
    n = t.num_rows
    if n == 0:
        return 0
    ts_vals = t.column(ts_col).to_pylist()
    col_lists = []
    for c in cols:
        arr = t.column(c)
        if pa.types.is_floating(arr.type):
            arr = pc.if_else(pc.is_nan(arr), pa.scalar(None, type=arr.type), arr)
        if c in INT_COLS:
            arr = pc.cast(arr, pa.int64(), safe=False)
        col_lists.append(arr.to_pylist())
    sql = f"COPY {table} (ts, instrument_id, {', '.join(cols)}) FROM STDIN"
    with _CONN.cursor() as cur:
        with cur.copy(sql) as copy:
            for row in zip(ts_vals, [iid] * n, *col_lists):
                copy.write_row(row)
    _CONN.commit()
    return n


# --------------------------------------------------------------------------- driver
def collect(root: Path, asset_types, only, limit):
    out = []
    for at in asset_types:
        d = root / at
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.parquet")):
            if only is not None and f.stem.upper() not in only:
                continue
            out.append((f, at))
    return out[:limit] if limit else out


def run_pool(tasks, workers, label):
    total = 0
    started = time.time()
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as ex:
        futs = [ex.submit(_copy_file, t) for t in tasks]
        for done, fut in enumerate(as_completed(futs), 1):
            total += fut.result()
            if done % 250 == 0 or done == len(tasks):
                el = time.time() - started
                print(f"  {label} {done:,}/{len(tasks):,} rows={total:,} "
                      f"{total/max(el,1):,.0f}/s {el:,.0f}s", file=sys.stderr, flush=True)
    return total


_REPO = Path(__file__).resolve().parents[2]

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--by-symbol-root", default=str(_REPO / "data" / "30min_data"))
    p.add_argument("--daily-root", default=str(_REPO / "data" / "daily_data"))
    p.add_argument("--scope", choices=["all", "stock", "etf"], default="all")
    p.add_argument("--symbols")
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=10)
    p.add_argument("--no-30min", action="store_true")
    p.add_argument("--no-daily", action="store_true")
    p.add_argument("--all-bars", action="store_true")
    # Schema is normally created by `make db-init` (db/schema/). --init-schema is for
    # standalone use; against the app DB it would DROP bars_30m (cascading the views).
    p.add_argument("--init-schema", action="store_true")
    p.add_argument("--schema-file", default=str(_REPO / "db" / "market_data" / "sql" / "002_features_schema.sql"))
    return p.parse_args()


def build_tasks(files, table, cols, ts_col, id_map, rth_only):
    tasks = []
    for f, at in files:
        iid = id_map[(stem_to_symbol(f.stem), at)]
        tasks.append((str(f), table, cols, ts_col, iid, rth_only))
    return tasks


def main() -> int:
    args = parse_args()
    asset_types = ["stock", "etf"] if args.scope == "all" else [args.scope]
    only = {s.strip().upper() for s in args.symbols.split(",")} if args.symbols else None
    rth_only = not args.all_bars

    files_30 = [] if args.no_30min else collect(Path(args.by_symbol_root), asset_types, only, args.limit)
    files_1d = [] if args.no_daily else collect(Path(args.daily_root), asset_types, only, args.limit)

    conn = connect()
    run_id = None
    try:
        if args.init_schema:
            print(f"applying schema {args.schema_file} ...", flush=True)
            init_schema(conn, args.schema_file)
        conn.execute("SET synchronous_commit TO off")
        conn.commit()

        # all instruments up front (derive symbol from filename) so workers never race
        inst = sorted({(stem_to_symbol(f.stem), at) for f, at in (files_30 + files_1d)})
        id_map = preload_instruments(conn, inst)
        print(f"instruments={len(id_map):,}", flush=True)
        run_id = start_run(conn, "features_parallel", args.scope, None, args.symbols, len(files_30) + len(files_1d))
        conn.commit()

        # drop PK + secondary indexes for a fast bulk load
        print("dropping PK + secondary indexes ...", flush=True)
        for tbl in ("bars_30m", "bars_1d"):
            conn.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS {tbl}_pkey")
        for name in SECONDARY_INDEXES:
            conn.execute(f"DROP INDEX IF EXISTS {name}")
        conn.commit()
        conn.close()  # free the connection; workers have their own

        total = d_total = 0
        if files_30:
            print(f"bars_30m: {len(files_30):,} files, workers={args.workers}, rth_only={rth_only}", flush=True)
            total = run_pool(build_tasks(files_30, "bars_30m", BARS_30M, "ts", id_map, rth_only), args.workers, "30m")
        if files_1d:
            print(f"bars_1d: {len(files_1d):,} files, workers={args.workers}", flush=True)
            d_total = run_pool(build_tasks(files_1d, "bars_1d", BARS_1D, "last_ts", id_map, False), args.workers, "1d")

        # rebuild PK + indexes once, with a big work_mem
        conn = connect()
        conn.execute("SET maintenance_work_mem TO '2GB'")
        conn.execute("SET max_parallel_maintenance_workers TO 4")
        conn.commit()
        for tbl, ddl in PK_DDL.items():
            print(f"rebuilding {tbl} primary key ...", flush=True)
            conn.execute(ddl)
            conn.commit()
        for name, ddl in SECONDARY_INDEXES.items():
            print(f"creating index {name} ...", flush=True)
            conn.execute(ddl)
            conn.commit()

        print("refreshing instrument bounds + ANALYZE ...", flush=True)
        conn.execute("""
            UPDATE instruments i SET first_ts = s.lo, last_ts = s.hi, updated_at = now()
            FROM (SELECT instrument_id, min(ts) lo, max(ts) hi FROM bars_30m GROUP BY instrument_id) s
            WHERE i.instrument_id = s.instrument_id
        """)
        conn.execute("ANALYZE bars_30m")
        conn.execute("ANALYZE bars_1d")
        conn.commit()
        finish_run(conn, run_id, "success", 0, total + d_total, total + d_total, 0)
        print(f"DONE: bars_30m={total:,} bars_1d={d_total:,}")
        return 0
    except Exception as exc:
        try:
            if run_id is not None:
                finish_run(conn, run_id, "failed", 0, 0, 0, 0, str(exc))
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
