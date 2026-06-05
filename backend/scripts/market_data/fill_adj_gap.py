"""Backfill missing adjusted prices: where adj_* is NaN but raw_* exists, set
adj_* := raw_*.

Rationale: the stock adj series is back-adjusted so that adj == raw at its anchor
(the last adj date, 2026-04-13, factor 1.0). The export-vintage hole 2026-04-14..05-19
left adj NaN while raw is present. Within that short window there is (almost) no
corporate action, so the correct continuation of the 04-13 anchoring is adj == raw.
Copying raw into the NaN-adj rows makes each symbol's adjusted series continuous,
with no dependency on external staging. Writes BASE columns only; rerun
compute_indicators.py afterwards to (re)derive indicators on the now-continuous series.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

BASE_COLUMNS = [
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
ADJ_FROM_RAW = [
    ("adj_open", "raw_open"),
    ("adj_high", "raw_high"),
    ("adj_low", "raw_low"),
    ("adj_close", "raw_close"),
    ("adj_volume", "raw_volume"),
]


def _fill(path_str: str):
    path = Path(path_str)
    try:
        df = pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        return (path.stem, -1, repr(exc))
    mask = df["adj_close"].isna() & df["raw_close"].notna()
    n = int(mask.sum())
    if n:
        for a, r in ADJ_FROM_RAW:
            df.loc[mask, a] = df.loc[mask, r].to_numpy()
    out = df[[c for c in BASE_COLUMNS if c in df.columns]]
    tmp = path.with_suffix(".parquet.tmp")
    out.to_parquet(tmp, engine="pyarrow", compression="zstd", index=False)
    os.replace(tmp, path)
    return (path.stem, n, "")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--by-symbol-root", default=r"D:\BaiduNetdiskDownload\30min\30min_data")
    p.add_argument("--scope", choices=["all", "stock", "etf"], default="all")
    p.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 1))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.by_symbol_root)
    ats = ["stock", "etf"] if args.scope == "all" else [args.scope]
    files = [str(f) for at in ats for f in sorted((root / at).glob("*.parquet"))]
    print(f"filling adj<-raw on {len(files):,} files, workers={args.workers}")

    started = time.time()
    filled_files = filled_rows = errs = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_fill, f) for f in files]
        for done, fut in enumerate(as_completed(futs), 1):
            stem, n, err = fut.result()
            if n < 0:
                errs += 1
                print(f"  ERR {stem}: {err}", file=sys.stderr)
            elif n > 0:
                filled_files += 1
                filled_rows += n
            if done % 1000 == 0:
                print(
                    f"  {done:,}/{len(files):,} elapsed={time.time() - started:,.0f}s",
                    file=sys.stderr,
                    flush=True,
                )
    print(
        f"done: files_with_fill={filled_files:,} rows_filled={filled_rows:,} errors={errs} "
        f"elapsed={time.time() - started:,.0f}s"
    )
    print("NEXT: python compute_indicators.py --scope all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
