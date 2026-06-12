"""Compute the bars_30m indicator family on a recent 1-min window and write it
back into market_data_1min's indicator columns.

Formulas mirror backend/scripts/market_data/compute_indicators.py (RTH-only, on
the close series). Recursive indicators (ema/rsi/atr/obv) are computed over a
rolling window (_WINDOW bars), so they're a close approximation of the
full-history values — fine for the live chart. vwap_day resets per ET day and is
exact as long as the window spans the current session.
"""

from __future__ import annotations

import asyncio
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import text

ET = ZoneInfo("America/New_York")
_WINDOW = 1500  # recent 1-min rows pulled per compute (warms sma_200 + spans today)
_RTH_START = 9 * 60 + 30  # 09:30 ET
_RTH_END = 16 * 60  # 16:00 ET

_IND_COLS = [
    "rth", "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "ema_50",
    "macd", "macd_signal", "macd_hist", "rsi_14",
    "bb_mid", "bb_upper", "bb_lower", "bb_pctb", "bb_bw",
    "atr_14", "obv", "vwap_day", "ret_1bar",
]

# Stored-precision policy by indicator category (see the long note in
# backend/scripts/market_data/compute_indicators.py:ROUND_DECIMALS — keep in sync).
# Price-derived + ratios/returns -> 4 dp, rsi_14 (0-100) -> 2 dp, obv (cum volume) -> 0.
_ROUND_DECIMALS: dict[str, int] = {
    "sma_20": 4, "sma_50": 4, "sma_200": 4, "ema_12": 4, "ema_26": 4, "ema_50": 4,
    "macd": 4, "macd_signal": 4, "macd_hist": 4,
    "bb_mid": 4, "bb_upper": 4, "bb_lower": 4, "bb_pctb": 4, "bb_bw": 4,
    "atr_14": 4, "vwap_day": 4, "ret_1bar": 4,
    "rsi_14": 2, "obv": 0,
}

_SELECT_SQL = text(
    "SELECT time, open, high, low, close, volume FROM market_data_1min "
    "WHERE ticker = :ticker ORDER BY time DESC LIMIT :window"
)
_UPDATE_SQL = text(
    "UPDATE market_data_1min SET "
    "rth=:rth, sma_20=:sma_20, sma_50=:sma_50, sma_200=:sma_200, "
    "ema_12=:ema_12, ema_26=:ema_26, ema_50=:ema_50, "
    "macd=:macd, macd_signal=:macd_signal, macd_hist=:macd_hist, rsi_14=:rsi_14, "
    "bb_mid=:bb_mid, bb_upper=:bb_upper, bb_lower=:bb_lower, bb_pctb=:bb_pctb, bb_bw=:bb_bw, "
    "atr_14=:atr_14, obv=:obv, vwap_day=:vwap_day, ret_1bar=:ret_1bar "
    "WHERE ticker=:ticker AND time=:time"
)


def common_indicator_block(
    close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series
) -> dict[str, pd.Series]:
    """The sma/ema/macd/rsi/bollinger/atr/obv family shared by bars_30m and bars_1d.

    Inputs are index-aligned price/volume series (RTH 30-min rows for the intraday
    store, the daily series for bars_1d). Recursive indicators (ema/rsi/atr/obv) use
    ``adjust=False`` so there is no lookahead. This is the single source of truth —
    the realtime 30-min compute below and the freshness backfill both call it, so the
    formulas can never drift apart.
    """
    block: dict[str, pd.Series] = {}
    for n in (20, 50, 200):
        block[f"sma_{n}"] = close.rolling(n, min_periods=n).mean()
    for n in (12, 26, 50):
        block[f"ema_{n}"] = close.ewm(span=n, adjust=False).mean()
    macd = block["ema_12"] - block["ema_26"]
    sig = macd.ewm(span=9, adjust=False).mean()
    block["macd"], block["macd_signal"], block["macd_hist"] = macd, sig, macd - sig
    delta = close.diff()
    ag = delta.clip(lower=0.0).ewm(alpha=1.0 / 14, adjust=False).mean()
    al = (-delta).clip(lower=0.0).ewm(alpha=1.0 / 14, adjust=False).mean()
    block["rsi_14"] = 100.0 - 100.0 / (1.0 + ag / al)
    mid = close.rolling(20, min_periods=20).mean()
    sd = close.rolling(20, min_periods=20).std(ddof=0)
    up, lo = mid + 2.0 * sd, mid - 2.0 * sd
    block["bb_mid"], block["bb_upper"], block["bb_lower"] = mid, up, lo
    block["bb_pctb"] = (close - lo) / (up - lo)
    block["bb_bw"] = (up - lo) / mid
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    block["atr_14"] = tr.ewm(alpha=1.0 / 14, adjust=False).mean()
    block["obv"] = (np.sign(close.diff().fillna(0.0)) * volume).cumsum()
    return block


def _compute(df: pd.DataFrame) -> pd.DataFrame:
    """df ascending by time with [time(UTC), open, high, low, close, volume].
    Adds rth + indicator columns (indicators only on RTH rows)."""
    et = df["time"].dt.tz_convert(ET)
    minutes = et.dt.hour * 60 + et.dt.minute
    rth = (minutes >= _RTH_START) & (minutes < _RTH_END)
    df = df.copy()
    df["rth"] = rth.to_numpy()
    for c in _IND_COLS[1:]:
        df[c] = np.nan

    sub = df.loc[rth]
    if sub.empty:
        return df
    close = sub["close"]
    block = common_indicator_block(close, sub["high"], sub["low"], sub["volume"])
    day = et.loc[sub.index].dt.normalize()
    tp = (sub["high"] + sub["low"] + sub["close"]) / 3.0
    cum_pv = (tp * sub["volume"]).groupby(day).cumsum()
    cum_v = sub["volume"].groupby(day).cumsum()
    block["vwap_day"] = cum_pv / cum_v
    block["ret_1bar"] = close.pct_change(1)
    for k, s in block.items():
        df.loc[sub.index, k] = s.to_numpy()
    return df


# Public alias: the freshness backfill rolls the 1-min stream up into 30-min bars and
# reuses this exact RTH/indicator computation for train/serve parity with bars_30m.
def compute_bar_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the bars_30m indicator family (rth + sma/ema/macd/rsi/bb/atr/obv/
    vwap_day/ret_1bar) on a [time, open, high, low, close, volume] frame. Returns a
    copy with the indicator columns added on RTH rows."""
    return _compute(df)


async def update_indicators(engine, ticker: str, *, tail: int = 8, full: bool = False) -> int:
    """Recompute indicators on a recent window; write the last `tail` bars (or the
    whole window if full=True) back into market_data_1min. Returns rows written."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(_SELECT_SQL, {"ticker": ticker, "window": _WINDOW})
        ).mappings().all()
    if len(rows) < 2:
        return 0
    df = pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)  # DESC -> ASC
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype("float64")
    out = await asyncio.to_thread(_compute, df)
    write = out if full else out.tail(tail)

    params: list[dict] = []
    for row in write.itertuples(index=False):
        d = row._asdict()
        rec: dict = {"ticker": ticker, "time": d["time"].to_pydatetime(), "rth": bool(d["rth"])}
        for c in _IND_COLS[1:]:
            v = d[c]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                rec[c] = None
            else:
                rec[c] = round(float(v), _ROUND_DECIMALS[c])
        params.append(rec)
    async with engine.begin() as conn:
        await conn.execute(_UPDATE_SQL, params)
    return len(params)
