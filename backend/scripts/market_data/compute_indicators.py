"""Compute technical indicators per symbol and write them into the parquet files.

Two outputs (user chose "both", regular trading hours 09:30-16:00 only):
  1. 30-min: indicator columns appended INTO each by_symbol/<asset>/<SYMBOL>.parquet.
     All original rows are kept; indicators are computed only on regular-session
     (RTH) bars, so pre/post-market rows get null indicators. An `rth` boolean
     column marks the regular-session rows.
  2. daily: RTH bars resampled to one bar per trading day, same indicator family
     plus multi-horizon day returns + overnight gap, written to
     features_daily/<asset>/<SYMBOL>.parquet.

Prices use adj_* (split/div-adjusted) so indicators don't jump on split dates.
Parallelized one task per symbol file (ProcessPoolExecutor).

Indicator math (period n is in *bars* for 30-min, in *days* for daily):
  sma_20/50/200     rolling mean of adj_close
  ema_12/26/50      adj_close.ewm(span=n, adjust=False)
  macd/signal/hist  EMA12-EMA26 ; EMA9(macd) ; macd-signal
  rsi_14            Wilder RMA of gains/losses (ewm alpha=1/14)
  bb_*              Bollinger(20,2sigma): mid/upper/lower/%B/bandwidth (ddof=0)
  atr_14            Wilder RMA of true range
  vwap_day          intraday, reset each trading day (typical price * vol)   [30-min only]
  obv               cumulative sign(close.diff()) * volume
  ret_1bar          adj_close.pct_change(1)                                   [30-min]
  ret_{1,5,21,63,126,252}d, gap_overnight                                    [daily]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

# scripts/ dir on path so we can reuse safe_filename
sys.path.insert(0, str(Path(__file__).resolve().parent))

RTH_START_MIN = 9 * 60 + 30  # 09:30
RTH_END_MIN = 16 * 60  # 16:00 (exclusive: last bar starts 15:30)

SMA_WINDOWS = (20, 50, 200)
EMA_SPANS = (12, 26, 50)
DAY_RETURN_HORIZONS = (1, 5, 21, 63, 126, 252)


# ----------------------------------------------------------------------------- indicators
def _price_block(close: pd.Series) -> dict[str, pd.Series]:
    """SMA / EMA / MACD / RSI / Bollinger off a single close series."""
    out: dict[str, pd.Series] = {}
    for n in SMA_WINDOWS:
        out[f"sma_{n}"] = close.rolling(n, min_periods=n).mean()
    for n in EMA_SPANS:
        out[f"ema_{n}"] = close.ewm(span=n, adjust=False).mean()

    ema12 = out["ema_12"]
    ema26 = out["ema_26"]
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    out["macd"] = macd
    out["macd_signal"] = signal
    out["macd_hist"] = macd - signal

    # RSI(14), Wilder smoothing via ewm(alpha=1/14, adjust=False)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss
    out["rsi_14"] = 100.0 - 100.0 / (1.0 + rs)

    # Bollinger(20, 2 population-sigma)
    mid = close.rolling(20, min_periods=20).mean()
    sd = close.rolling(20, min_periods=20).std(ddof=0)
    upper = mid + 2.0 * sd
    lower = mid - 2.0 * sd
    width = upper - lower
    out["bb_mid"] = mid
    out["bb_upper"] = upper
    out["bb_lower"] = lower
    out["bb_pctb"] = (close - lower) / width
    out["bb_bw"] = width / mid
    return out


def _atr14(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / 14, adjust=False).mean()


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    sign = np.sign(close.diff().fillna(0.0))
    return (sign * volume).cumsum()


def _common_indicators(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Indicators shared by 30-min and daily (adj_* OHLCV, contiguous rows)."""
    close = df["adj_close"]
    out = _price_block(close)
    out["atr_14"] = _atr14(df["adj_high"], df["adj_low"], close)
    out["obv"] = _obv(close, df["adj_volume"].astype("float64"))
    return out


_BLOCK_KEYS = [
    "sma_20",
    "sma_50",
    "sma_200",
    "ema_12",
    "ema_26",
    "ema_50",
    "macd",
    "macd_signal",
    "macd_hist",
    "rsi_14",
    "bb_mid",
    "bb_upper",
    "bb_lower",
    "bb_pctb",
    "bb_bw",
    "atr_14",
    "obv",
]


def _segment_id(adj_close: pd.Series, raw_close: pd.Series) -> pd.Series:
    """Segment id incrementing at adjustment discontinuities (adj jumps >30% while raw
    doesn't = a broken/missing split factor at an era boundary). Indicators are reset per
    segment so a bad boundary bar can't pollute the recursive indicators across eras."""
    ar = adj_close.pct_change()
    rr = raw_close.pct_change()
    brk = (ar.sub(rr).abs() > 0.05) & (ar.abs() > 0.30)
    return brk.fillna(False).cumsum()


def _common_indicators_seg(df: pd.DataFrame, seg: pd.Series) -> dict[str, pd.Series]:
    """_common_indicators computed independently per segment (reset at boundaries)."""
    if seg.nunique() <= 1:
        return _common_indicators(df)
    out = {k: pd.Series(np.nan, index=df.index, dtype="float64") for k in _BLOCK_KEYS}
    for _, g in df.groupby(seg, sort=False):
        for k, s in _common_indicators(g).items():
            out[k].loc[s.index] = s.to_numpy()
    return out


# ----------------------------------------------------------------------------- per-file work
def _rth_minutes(et_time: pd.Series) -> pd.Series:
    return et_time.dt.hour * 60 + et_time.dt.minute


def _process_30min(df: pd.DataFrame) -> pd.DataFrame:
    """Append indicator columns + rth flag to the full-history frame (rows kept)."""
    minutes = _rth_minutes(df["et_time"])
    rth = (minutes >= RTH_START_MIN) & (minutes < RTH_END_MIN)
    df = df.copy()
    df["rth"] = rth.to_numpy()

    # Compute only where adj price exists. Otherwise ewm/cumsum-based indicators
    # (RSI/EMA/MACD/ATR/OBV) would carry the last valid value forward over the
    # missing-adj tail, silently faking a current signal. Excluded rows -> NaN.
    sub = df.loc[rth & df["adj_close"].notna()].copy()
    if sub.empty:
        return df
    sub = sub.sort_values("ts")

    seg = _segment_id(sub["adj_close"], sub["raw_close"])
    block = _common_indicators_seg(sub, seg)
    # intraday VWAP, reset every trading day
    day = sub["et_time"].dt.normalize()
    tp = (sub["adj_high"] + sub["adj_low"] + sub["adj_close"]) / 3.0
    vol = sub["adj_volume"].astype("float64")
    cum_pv = (tp * vol).groupby(day).cumsum()
    cum_v = vol.groupby(day).cumsum()
    block["vwap_day"] = cum_pv / cum_v
    block["ret_1bar"] = sub["adj_close"].groupby(seg).pct_change(1)  # resets per segment

    for name, series in block.items():
        col = pd.Series(np.nan, index=df.index, dtype="float64")
        col.loc[series.index] = series.to_numpy()
        df[name] = col
    return df


def _process_daily(df: pd.DataFrame, symbol: str, asset_type: str) -> pd.DataFrame:
    """Resample RTH bars to daily OHLCV and compute the daily indicator set."""
    minutes = _rth_minutes(df["et_time"])
    rth = (minutes >= RTH_START_MIN) & (minutes < RTH_END_MIN)
    # Only bars with a real adj price (see _process_30min note); days without any
    # adjusted data simply don't appear in the daily series instead of freezing.
    sub = df.loc[rth & df["adj_close"].notna()].sort_values("ts")
    if sub.empty:
        return pd.DataFrame()

    day = sub["et_time"].dt.normalize()
    grp = sub.groupby(day, sort=True)
    daily = pd.DataFrame(
        {
            "date": grp["et_time"].first().dt.normalize().to_numpy(),
            "adj_open": grp["adj_open"].first().to_numpy(),
            "adj_high": grp["adj_high"].max().to_numpy(),
            "adj_low": grp["adj_low"].min().to_numpy(),
            "adj_close": grp["adj_close"].last().to_numpy(),
            "adj_volume": grp["adj_volume"].sum().to_numpy(),
            "raw_close": grp["raw_close"].last().to_numpy(),
            "rth_bars": grp.size().to_numpy(),
            "last_ts": grp["ts"].last().to_numpy(),
        }
    )
    daily.insert(0, "symbol", symbol)
    daily.insert(1, "asset_type", asset_type)
    daily = daily.reset_index(drop=True)

    seg = _segment_id(daily["adj_close"], daily["raw_close"])
    block = _common_indicators_seg(daily, seg)
    for name, series in block.items():
        daily[name] = series.to_numpy()

    close = daily["adj_close"]
    for h in DAY_RETURN_HORIZONS:
        daily[f"ret_{h}d"] = close.groupby(seg).pct_change(h).to_numpy()
    daily["gap_overnight"] = (daily["adj_open"] / close.groupby(seg).shift(1) - 1.0).to_numpy()
    return daily


# ----------------------------------------------------------------------------- precision
# Output rounding by indicator category, to standardize stored precision.
#   - Price-denominated values (OHLC + all price-derived indicators) keep 4 decimals:
#     sub-cent resolution, safe for split-adjusted history and sub-$1 names, and matches
#     market_data_1min's NUMERIC(14,4).
#   - Bounded ratios and returns also keep 4 (2 would collapse e.g. 0.0023 -> 0.00).
#   - rsi_14 is a 0-100 oscillator: 2 decimals is plenty.
#   - obv is whole-share cumulative volume: 0 decimals.
# MIRRORED by data/ingestion/realtime/indicators.py (realtime 1-min compute) and
# backend/scripts/market_data/round_existing_precision.py (one-time DB backfill).
# Keep the three in sync.
ROUND_DECIMALS: dict[str, int] = {
    # prices + price-derived (4)
    "raw_open": 4, "raw_high": 4, "raw_low": 4, "raw_close": 4,
    "adj_open": 4, "adj_high": 4, "adj_low": 4, "adj_close": 4,
    "sma_20": 4, "sma_50": 4, "sma_200": 4,
    "ema_12": 4, "ema_26": 4, "ema_50": 4,
    "macd": 4, "macd_signal": 4, "macd_hist": 4,
    "bb_mid": 4, "bb_upper": 4, "bb_lower": 4,
    "atr_14": 4, "vwap_day": 4,
    # bounded ratios + returns (4)
    "bb_pctb": 4, "bb_bw": 4, "ret_1bar": 4,
    "ret_1d": 4, "ret_5d": 4, "ret_21d": 4,
    "ret_63d": 4, "ret_126d": 4, "ret_252d": 4,
    "gap_overnight": 4,
    # bounded oscillator (2)
    "rsi_14": 2,
    # cumulative volume (0)
    "obv": 0,
}


def round_precision(df: pd.DataFrame) -> pd.DataFrame:
    """Round price/indicator columns to their per-category precision (NaN preserved,
    volume/non-numeric columns untouched). Returns a rounded copy."""
    cols = {c: n for c, n in ROUND_DECIMALS.items() if c in df.columns}
    return df.round(cols) if cols else df


def _atomic_write(table_df: pd.DataFrame, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    table_df.to_parquet(tmp, engine="pyarrow", compression="zstd", index=False)
    os.replace(tmp, dest)


def _task(
    src_path: str,
    asset_type: str,
    do_30min: bool,
    do_daily: bool,
    min30_out_dir: str | None,
    daily_root: str | None,
):
    src = Path(src_path)
    symbol = src.stem  # already safe_filename'd at export time
    try:
        df = pd.read_parquet(src, engine="pyarrow")
    except Exception as exc:  # noqa: BLE001
        return (symbol, "read_error", repr(exc), 0, 0)

    n_in = len(df)
    n_daily = 0
    try:
        if do_30min:
            out_df = round_precision(_process_30min(df))
            if min30_out_dir:
                dest = Path(min30_out_dir) / asset_type / src.name
            else:
                dest = src  # in-place
            _atomic_write(out_df, dest)
        if do_daily and daily_root:
            daily = round_precision(_process_daily(df, symbol, asset_type))
            n_daily = len(daily)
            if n_daily:
                _atomic_write(daily, Path(daily_root) / asset_type / src.name)
    except Exception as exc:  # noqa: BLE001
        return (symbol, "compute_error", repr(exc), n_in, n_daily)
    return (symbol, "ok", "", n_in, n_daily)


# ----------------------------------------------------------------------------- driver
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compute indicators per symbol (30-min in-place + daily)."
    )
    p.add_argument("--by-symbol-root", default=r"D:\BaiduNetdiskDownload\30min\30min_data")
    p.add_argument("--daily-root", default=r"D:\BaiduNetdiskDownload\30min\daily_data")
    p.add_argument("--scope", choices=["all", "stock", "etf"], default="all")
    p.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 1))
    p.add_argument("--no-30min", action="store_true", help="Skip the 30-min in-place pass.")
    p.add_argument("--no-daily", action="store_true", help="Skip the daily features pass.")
    p.add_argument(
        "--min30-out-dir",
        default=None,
        help="If set, write 30-min output here instead of overwriting by_symbol files (smoke/safe mode).",
    )
    p.add_argument(
        "--only", nargs="*", default=None, help="Process only these symbols (smoke test)."
    )
    p.add_argument(
        "--limit", type=int, default=None, help="Process only the first N files (smoke test)."
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.by_symbol_root)
    do_30min = not args.no_30min
    do_daily = not args.no_daily

    asset_types = ["stock", "etf"] if args.scope == "all" else [args.scope]
    only = {s.upper() for s in args.only} if args.only else None

    tasks: list[tuple[str, str]] = []
    for at in asset_types:
        d = root / at
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.parquet")):
            if only is not None and f.stem.upper() not in only:
                continue
            tasks.append((str(f), at))
    if args.limit:
        tasks = tasks[: args.limit]

    print(
        f"plan: {len(tasks):,} files | 30min={do_30min} daily={do_daily} | workers={args.workers}"
    )
    if args.min30_out_dir:
        print(f"  30-min output -> {args.min30_out_dir} (NOT overwriting originals)")
    elif do_30min:
        print("  30-min output -> IN-PLACE into by_symbol files")

    started = time.time()
    ok = 0
    errors: list[tuple[str, str, str]] = []
    rows_30 = 0
    rows_daily = 0

    def handle(res):
        nonlocal ok, rows_30, rows_daily
        symbol, status, msg, n_in, n_daily = res
        if status == "ok":
            ok += 1
            rows_30 += n_in
            rows_daily += n_daily
        else:
            errors.append((symbol, status, msg))

    if args.workers == 1:
        for src, at in tasks:
            handle(_task(src, at, do_30min, do_daily, args.min30_out_dir, args.daily_root))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = [
                ex.submit(_task, src, at, do_30min, do_daily, args.min30_out_dir, args.daily_root)
                for src, at in tasks
            ]
            for done, fut in enumerate(as_completed(futs), start=1):
                handle(fut.result())
                if done % 250 == 0 or done == len(tasks):
                    print(
                        f"  progress {done:,}/{len(tasks):,}  ok={ok:,} err={len(errors):,} "
                        f"elapsed={time.time() - started:,.0f}s",
                        file=sys.stderr,
                        flush=True,
                    )

    print(
        f"\ndone: ok={ok:,} errors={len(errors):,} "
        f"30min_rows={rows_30:,} daily_rows={rows_daily:,} elapsed={time.time() - started:,.0f}s"
    )
    for symbol, status, msg in errors[:20]:
        print(f"  ERR {symbol}: {status} {msg}", file=sys.stderr)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
