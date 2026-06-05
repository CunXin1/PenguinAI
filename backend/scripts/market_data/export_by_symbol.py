"""Export one Parquet file per ACTIVE symbol: by_symbol/<asset_type>/<SYMBOL>.parquet.

Each file holds that symbol's full 2000-2026 history, sorted by ts, with raw_* and
adj_* (unadjusted + split/div-adjusted) in the same rows -- ready for downstream
indicator work (MACD/VWAP etc). Delisted symbols (per symbol_stats.py) are skipped.

Parallelized by (asset_type, first-letter bucket): partition pruning means each
task reads only its own bucket across all years.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq


def bucket_for(symbol: str) -> str:
    """First-letter bucket (A-Z, else '_'). Inlined from the removed build_parquet_copy."""
    first = symbol[0].upper() if symbol else "_"
    return first if "A" <= first <= "Z" else "_"


OUT_COLUMNS = [
    "ts",
    "et_time",
    "symbol",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "raw_volume",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "adj_volume",
]

_SAFE = re.compile(r"[^A-Za-z0-9._-]")
# Windows reserved device names cannot be used as a file stem even with an extension.
_RESERVED = (
    {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    | {f"COM{i}" for i in range(10)}
    | {f"LPT{i}" for i in range(10)}
)


def safe_filename(symbol: str) -> str:
    name = _SAFE.sub("_", symbol)
    if name.upper() in _RESERVED:
        name += "_"
    return name


def load_active(stats_path: Path) -> dict[str, set[str]]:
    """asset_type -> set of active symbols."""
    t = pq.read_table(stats_path)
    t = t.filter(pc.field("active"))
    out: dict[str, set[str]] = defaultdict(set)
    ats = t.column("asset_type").to_pylist()
    syms = t.column("symbol").to_pylist()
    for at, sym in zip(ats, syms, strict=False):
        out[at].add(sym)
    return out


def _export_bucket(parquet_root, out_root, asset_type, bucket, active_symbols, row_group_rows):
    started = time.time()
    bars = str(Path(parquet_root) / "bars_30m")
    dataset = ds.dataset(bars, format="parquet", partitioning="hive")
    flt = (pc.field("asset_type") == asset_type) & (pc.field("bucket") == bucket)
    table = dataset.to_table(columns=OUT_COLUMNS, filter=flt)
    if table.num_rows == 0:
        return (0, 0)

    table = table.sort_by([("symbol", "ascending"), ("ts", "ascending")])
    sym_arr = pa.concat_arrays(table.column("symbol").chunks)
    ree = pc.run_end_encode(sym_arr)
    run_ends = ree.run_ends.to_pylist()
    values = ree.values.to_pylist()

    out_dir = Path(out_root) / asset_type
    out_dir.mkdir(parents=True, exist_ok=True)

    files = 0
    rows = 0
    prev = 0
    for value, end in zip(values, run_ends, strict=False):
        length = end - prev
        if value in active_symbols:
            sub = table.slice(prev, length)
            pq.write_table(
                sub,
                out_dir / f"{safe_filename(value)}.parquet",
                compression="zstd",
                use_dictionary=["symbol"],
                row_group_size=row_group_rows,
            )
            files += 1
            rows += length
        prev = end

    print(
        f"[{asset_type}] bucket={bucket} files={files:,} rows={rows:,} t={time.time() - started:,.0f}s",
        file=sys.stderr,
        flush=True,
    )
    return (files, rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export one Parquet per active symbol.")
    p.add_argument("--parquet-root", default=r"D:\BaiduNetdiskDownload\30min\parquet_market")
    p.add_argument(
        "--stats", default=r"D:\BaiduNetdiskDownload\30min\30min_data\_symbol_stats.parquet"
    )
    p.add_argument("--out-root", default=r"D:\BaiduNetdiskDownload\30min\30min_data")
    p.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    p.add_argument("--row-group-rows", type=int, default=100_000)
    p.add_argument("--scope", choices=["all", "stocks", "etfs"], default="all")
    p.add_argument("--limit-buckets", type=int, help="Only process first N tasks (smoke test).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    active = load_active(Path(args.stats))
    total_active = sum(len(v) for v in active.values())
    print(
        "active symbols: "
        + ", ".join(f"{k}={len(v):,}" for k, v in sorted(active.items()))
        + f"  total={total_active:,}"
    )

    asset_types = []
    if args.scope in {"all", "stocks"}:
        asset_types.append("stock")
    if args.scope in {"all", "etfs"}:
        asset_types.append("etf")

    # group active symbols by (asset_type, bucket)
    tasks = []
    for at in asset_types:
        by_bucket: dict[str, set[str]] = defaultdict(set)
        for sym in active.get(at, set()):
            by_bucket[bucket_for(sym)].add(sym)
        for bucket, syms in sorted(by_bucket.items()):
            tasks.append((at, bucket, syms))
    if args.limit_buckets:
        tasks = tasks[: args.limit_buckets]

    print(f"plan: {len(tasks)} (asset_type,bucket) tasks across {args.workers} worker(s)")

    total_files = 0
    total_rows = 0
    started = time.time()

    def run(task):
        at, bucket, syms = task
        return _export_bucket(
            args.parquet_root, args.out_root, at, bucket, syms, args.row_group_rows
        )

    if args.workers == 1:
        for task in tasks:
            f, r = run(task)
            total_files += f
            total_rows += r
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {
                ex.submit(
                    _export_bucket,
                    args.parquet_root,
                    args.out_root,
                    at,
                    bucket,
                    syms,
                    args.row_group_rows,
                ): (at, bucket)
                for (at, bucket, syms) in tasks
            }
            for done, fut in enumerate(as_completed(futs), start=1):
                f, r = fut.result()
                total_files += f
                total_rows += r
                print(
                    f"progress: {done}/{len(tasks)} tasks, files={total_files:,} rows={total_rows:,} "
                    f"elapsed={time.time() - started:,.0f}s",
                    file=sys.stderr,
                    flush=True,
                )

    print(f"done files={total_files:,} rows={total_rows:,} elapsed={time.time() - started:,.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
