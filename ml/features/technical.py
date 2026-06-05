"""
Technical indicator computation on 30-min OHLCV data.
Uses pandas-ta for all indicator calculations.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pandas_ta as ta


@dataclass
class IndicatorFeatures:
    """Flat feature dict ready to feed into XGBoost / RF."""

    rsi_14: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    bb_pct_b: float | None  # position within Bollinger Bands (0–1)
    bb_width: float | None  # bandwidth normalized
    atr_14_pct: float | None  # ATR as % of close price
    ema20_slope: float | None  # rate of change of EMA-20 over last 3 bars
    price_vs_sma200: float | None  # close / SMA-200 - 1
    volume_ratio: float | None  # current vol / 20-bar avg vol
    vwap_pct: float | None  # (close - vwap) / vwap


def compute_features(df: pd.DataFrame) -> IndicatorFeatures:
    """
    Compute all technical features from OHLCV DataFrame.

    Args:
        df: DataFrame with columns [time, open, high, low, close, volume]
            sorted by time ascending. Minimum 200 rows for SMA-200.

    Returns:
        IndicatorFeatures for the LAST bar (most recent).
    """
    if len(df) < 20:
        return IndicatorFeatures(**dict.fromkeys(IndicatorFeatures.__dataclass_fields__))

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    # RSI
    rsi = ta.rsi(close, length=14)

    # MACD
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)

    # Bollinger Bands
    bb = ta.bbands(close, length=20, std=2)

    # ATR
    atr = ta.atr(high, low, close, length=14)

    # EMAs / SMA
    ema20 = ta.ema(close, length=20)
    sma200 = ta.sma(close, length=200) if len(df) >= 200 else pd.Series([None] * len(df))

    # Volume ratio
    vol_sma20 = volume.rolling(20).mean()

    last = -1

    # %B = (close - lower) / (upper - lower)
    bb_pct_b = None
    bb_width = None
    if bb is not None and not bb.empty:
        upper_col = [c for c in bb.columns if "BBU" in c][0]
        lower_col = [c for c in bb.columns if "BBL" in c][0]
        mid_col = [c for c in bb.columns if "BBM" in c][0]
        upper = bb[upper_col].iloc[last]
        lower = bb[lower_col].iloc[last]
        mid = bb[mid_col].iloc[last]
        if pd.notna(upper) and pd.notna(lower) and upper != lower:
            bb_pct_b = (close.iloc[last] - lower) / (upper - lower)
            bb_width = (upper - lower) / mid if mid else None

    # EMA-20 slope (3-bar rate of change)
    ema20_slope = None
    if (
        ema20 is not None
        and len(ema20) >= 4
        and pd.notna(ema20.iloc[last])
        and pd.notna(ema20.iloc[-4])
    ):
        ema20_slope = (ema20.iloc[last] - ema20.iloc[-4]) / ema20.iloc[-4]

    # Price vs SMA-200
    price_vs_sma200 = None
    s200 = sma200.iloc[last] if sma200 is not None else None
    if pd.notna(s200) and s200 > 0:
        price_vs_sma200 = (close.iloc[last] / s200) - 1

    # Volume ratio
    vol_avg = vol_sma20.iloc[last]
    volume_ratio = (volume.iloc[last] / vol_avg) if pd.notna(vol_avg) and vol_avg > 0 else None

    # ATR as % of close
    atr_val = atr.iloc[last] if atr is not None else None
    atr_14_pct = (
        (atr_val / close.iloc[last]) if pd.notna(atr_val) and close.iloc[last] > 0 else None
    )

    # VWAP (use session VWAP if available in df, else compute simple approximation)
    vwap_pct = None
    if "vwap" in df.columns and pd.notna(df["vwap"].iloc[last]):
        vwap_val = float(df["vwap"].iloc[last])
        if vwap_val > 0:
            vwap_pct = (close.iloc[last] - vwap_val) / vwap_val

    cols = list(macd_df.columns) if macd_df is not None and not macd_df.empty else []
    macd_col = [c for c in cols if "MACD_" in c and "MACDs" not in c and "MACDh" not in c]
    macds_col = [c for c in cols if "MACDs" in c]
    macdh_col = [c for c in cols if "MACDh" in c]

    return IndicatorFeatures(
        rsi_14=_safe(rsi, last),
        macd=_safe(macd_df[macd_col[0]], last) if macd_col else None,
        macd_signal=_safe(macd_df[macds_col[0]], last) if macds_col else None,
        macd_hist=_safe(macd_df[macdh_col[0]], last) if macdh_col else None,
        bb_pct_b=bb_pct_b,
        bb_width=bb_width,
        atr_14_pct=atr_14_pct,
        ema20_slope=ema20_slope,
        price_vs_sma200=price_vs_sma200,
        volume_ratio=volume_ratio,
        vwap_pct=vwap_pct,
    )


def _safe(series: pd.Series, idx: int) -> float | None:
    try:
        val = series.iloc[idx]
        return float(val) if pd.notna(val) else None
    except Exception:
        return None


def features_to_dict(f: IndicatorFeatures) -> dict[str, float]:
    """Convert to flat dict, replacing None with NaN for XGBoost."""
    return {k: (v if v is not None else np.nan) for k, v in f.__dict__.items()}
