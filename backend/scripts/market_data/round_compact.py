"""Shrink the per-symbol parquet by rounding prices/indicators to a sensible number
of decimals and downcasting float64 -> float32.

Why both: in Parquet a float64 is always 8 bytes regardless of how many decimals it
prints, so rounding alone barely helps. The real win is float32 (4 bytes, ~7
significant digits -- plenty for prices and indicators, and it drops the long binary
mantissa tail). Rounding on top makes values clean and compresses a little better.

In-place, atomic per file, parallel. Re-run this after any recompute (compute_indicators
writes float64 again).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

# column -> decimals
DECIMALS = {
    "raw_open": 4,
    "raw_high": 4,
    "raw_low": 4,
    "raw_close": 4,
    "adj_open": 4,
    "adj_high": 4,
    "adj_low": 4,
    "adj_close": 4,
    "sma_20": 4,
    "sma_50": 4,
    "sma_200": 4,
    "ema_12": 4,
    "ema_26": 4,
    "ema_50": 4,
    "macd": 4,
    "macd_signal": 4,
    "macd_hist": 4,
    "rsi_14": 2,
    "bb_mid": 4,
    "bb_upper": 4,
    "bb_lower": 4,
    "bb_pctb": 4,
    "bb_bw": 4,
    "atr_14": 4,
    "vwap_day": 4,
    "obv": 0,
    "ret_1bar": 4,
    "ret_1d": 4,
    "ret_5d": 4,
    "ret_21d": 4,
    "ret_63d": 4,
    "ret_126d": 4,
    "ret_252d": 4,
    "gap_overnight": 4,
}
# rounded but kept float64 (large cumulative values lose precision in float32)
KEEP_FLOAT64 = {"obv"}


def _process(path_str: str, to_float32: bool):
    path = Path(path_str)
    try:
        before = path.stat().st_size
        df = pd.read_parquet(path)
        for col, nd in DECIMALS.items():
            if col not in df.columns:
                continue
            df[col] = df[col].round(nd)
            if to_float32 and col not in KEEP_FLOAT64:
                df[col] = df[col].astype("float32")
        tmp = path.with_suffix(".parquet.tmp")
        df.to_parquet(tmp, engine="pyarrow", compression="zstd", index=False)
        os.replace(tmp, path)
        after = path.stat().st_size
        return (before, after, None)
    except Exception as exc:  # noqa: BLE001
        return (0, 0, f"{path.name}: {exc!r}")


def collect(roots, scope):
    ats = ["stock", "etf"] if scope == "all" else [scope]
    files = []
    for root in roots:
        for at in ats:
            d = Path(root) / at
            if d.is_dir():
                files += [str(f) for f in sorted(d.glob("*.parquet"))]
    return files


def parse_args():
    p = argparse.ArgumentParser(description="Round + float32 the per-symbol parquet to save space.")
    p.add_argument("--by-symbol-root", default=r"D:\BaiduNetdiskDownload\30min\30min_data")
    p.add_argument("--daily-root", default=r"D:\BaiduNetdiskDownload\30min\daily_data")
    p.add_argument("--scope", choices=["all", "stock", "etf"], default="all")
    p.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 1))
    p.add_argument(
        "--no-float32", action="store_true", help="Round only, keep float64 (smaller win)."
    )
    p.add_argument("--only-by-symbol", action="store_true")
    p.add_argument("--only-daily", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--symbols", nargs="*")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    roots = []
    if not args.only_daily:
        roots.append(args.by_symbol_root)
    if not args.only_by_symbol:
        roots.append(args.daily_root)
    files = collect(roots, args.scope)
    if args.symbols:
        only = {s.upper() for s in args.symbols}
        files = [f for f in files if Path(f).stem.upper() in only]
    if args.limit:
        files = files[: args.limit]
    to_f32 = not args.no_float32
    print(f"files={len(files):,}  float32={to_f32}  workers={args.workers}")

    started = time.time()
    tb = ta = errs = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_process, f, to_f32) for f in files]
        for done, fut in enumerate(as_completed(futs), 1):
            b, a, err = fut.result()
            if err:
                errs += 1
                print("  ERR " + err, file=sys.stderr)
            else:
                tb += b
                ta += a
            if done % 1000 == 0:
                print(
                    f"  {done:,}/{len(files):,} elapsed={time.time() - started:,.0f}s",
                    file=sys.stderr,
                    flush=True,
                )
    gb = 1024**3
    print(
        f"done: before={tb / gb:.2f} GB  after={ta / gb:.2f} GB  saved={(tb - ta) / gb:.2f} GB "
        f"({(1 - ta / tb) * 100:.0f}%)  errors={errs}  elapsed={time.time() - started:,.0f}s"
    )
    return 0 if errs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
