"""Keep bars_30m / bars_1d current by rolling the live 1-min stream forward.

The 30-min and daily bar stores are batch-loaded from parquet (``make import-30min``)
and nothing appends recent sessions, so they drift stale between imports. This module
detects that drift and repairs it — on backend startup and once daily — for the seed
(streamed) universe:

  primary  — roll up ``market_data_1min`` (RTH only) into 30-min / daily OHLCV and
             recompute the FULL indicator family via the shared
             ``data.ingestion.realtime.indicators`` helpers, so backfilled bars carry
             the same sma/ema/macd/rsi/bb/atr/obv (+ vwap_day/ret_1bar for 30-min,
             + multi-horizon returns/gap for daily) as imported bars → train/serve
             parity is preserved (``indicators_30min`` / ``FEATURE_SQL`` stay valid).
  fallback — symbols with no 1-min coverage are caught up from the Massive REST API
             (reusing ``seed_market_data``), OHLCV only.

Runs in a BACKGROUND THREAD with its own event loop (asyncio.run), so it uses
``seed_market_data._make_session()`` — a fresh engine per loop (asyncpg pools are
bound to the loop that created them).

Completeness guards (never write in-progress bars):
  - 30-min: a bucket is written only once ``bucket_ts + 30min <= max(1-min time)``.
  - daily:  a session is written only once it has settled (latest 1-min time is past
            16:00 ET for that date, else the date is excluded until the next run).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.core.config import settings
from app.core.seed_market_data import (
    _asset_type,
    _ensure_instrument,
    _get_seed_tickers,
    _make_session,
)
from data.ingestion.realtime.indicators import common_indicator_block, compute_bar_indicators

logger = logging.getLogger("app.freshness")

ET = ZoneInfo("America/New_York")
_DAY_RETURN_HORIZONS = (1, 5, 21, 63, 126, 252)

# Lookback for the 30-min rollup window. Must comfortably exceed the sma_200 warmup
# (200 RTH 30-min bars ≈ 16 trading days) so backfilled bars have valid indicators.
_WARMUP_30M_DAYS = 40
# Warmup rows pulled from existing bars_1d so daily indicators (sma_200, ret_252d)
# are exact for newly appended sessions.
_WARMUP_1D_ROWS = 320

# RTH window filter shared by both rollups (09:30–16:00 ET, Mon–Fri).
_RTH_FILTER = (
    "(time AT TIME ZONE 'America/New_York')::time >= time '09:30' "
    "AND (time AT TIME ZONE 'America/New_York')::time < time '16:00' "
    "AND extract(dow FROM time AT TIME ZONE 'America/New_York') BETWEEN 1 AND 5"
)

_30M_INSERT_COLS = [
    "ts", "instrument_id", "rth",
    "raw_open", "raw_high", "raw_low", "raw_close", "raw_volume",
    "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
    "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "ema_50",
    "macd", "macd_signal", "macd_hist", "rsi_14",
    "bb_mid", "bb_upper", "bb_lower", "bb_pctb", "bb_bw",
    "atr_14", "obv", "vwap_day", "ret_1bar",
]

_1D_INSERT_COLS = [
    "ts", "instrument_id", "rth_bars", "raw_close",
    "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
    "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "ema_50",
    "macd", "macd_signal", "macd_hist", "rsi_14",
    "bb_mid", "bb_upper", "bb_lower", "bb_pctb", "bb_bw",
    "atr_14", "obv",
    "ret_1d", "ret_5d", "ret_21d", "ret_63d", "ret_126d", "ret_252d",
    "gap_overnight",
]


def _clean(v) -> float | None:
    """NaN / None → SQL NULL; otherwise a plain float."""
    if v is None:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    return float(v)


def _upsert_sql(table: str, cols: list[str]) -> str:
    placeholders = ", ".join(f":{c}" for c in cols)
    update = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("ts", "instrument_id"))
    return (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT (ts, instrument_id) DO UPDATE SET {update}"
    )


# ---------------------------------------------------------------------------
# 30-min backfill (1-min rollup + indicators)
# ---------------------------------------------------------------------------


async def _backfill_30m(db, symbol: str, iid: int) -> int:
    last_ts = (
        await db.execute(
            text("SELECT max(ts) FROM bars_30m WHERE instrument_id = :iid"), {"iid": iid}
        )
    ).scalar()

    rows = (
        await db.execute(
            text(f"""
                WITH mx AS (SELECT max(time) AS m FROM market_data_1min WHERE ticker = :sym)
                SELECT time_bucket('30 minutes', time) AS ts,
                       first(open, time)  AS open,
                       max(high)          AS high,
                       min(low)           AS low,
                       last(close, time)  AS close,
                       sum(volume)        AS volume
                FROM market_data_1min, mx
                WHERE ticker = :sym
                  AND time >= now() - make_interval(days => :warmup)
                  AND {_RTH_FILTER}
                GROUP BY ts
                HAVING time_bucket('30 minutes', time) + interval '30 minutes' <= (SELECT m FROM mx)
                ORDER BY ts
            """),
            {"sym": symbol, "warmup": _WARMUP_30M_DAYS},
        )
    ).mappings().all()
    if len(rows) < 2:
        return 0

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["ts"], utc=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype("float64")
    out = compute_bar_indicators(df)

    new = out if last_ts is None else out[out["time"] > last_ts]
    new = new[new["rth"]]
    if new.empty:
        return 0

    sql = text(_upsert_sql("bars_30m", _30M_INSERT_COLS))
    params = []
    for r in new.itertuples(index=False):
        d = r._asdict()
        o, h, lo, c, v = d["open"], d["high"], d["low"], d["close"], d["volume"]
        # Recent live bars have no split/dividend events, so raw == adj.
        rec = {
            "ts": d["time"].to_pydatetime(), "instrument_id": iid, "rth": True,
            "raw_open": o, "raw_high": h, "raw_low": lo, "raw_close": c, "raw_volume": int(v),
            "adj_open": o, "adj_high": h, "adj_low": lo, "adj_close": c, "adj_volume": int(v),
        }
        for col in _30M_INSERT_COLS:
            if col not in rec:
                rec[col] = _clean(d[col])
        params.append(rec)

    await db.execute(sql, params)
    return len(params)


# ---------------------------------------------------------------------------
# Daily backfill (1-min → session rollup + indicators + multi-horizon returns)
# ---------------------------------------------------------------------------


async def _backfill_1d(db, symbol: str, iid: int) -> int:
    last_ts = (
        await db.execute(
            text("SELECT max(ts) FROM bars_1d WHERE instrument_id = :iid"), {"iid": iid}
        )
    ).scalar()
    # Cutoff as a native ET date. Passed as a date object (asyncpg binds it directly,
    # no ::date cast) and placed BEFORE the interpolated _RTH_FILTER below — a named
    # param that follows that quote/colon-heavy fragment isn't parsed by text().
    last_date = last_ts.astimezone(ET).date() if last_ts else date(1900, 1, 1)

    # New settled sessions rolled up from the 1-min stream. The daily bar's ts matches
    # the import convention: the session's last RTH 30-min bucket (15:30 ET / 19:30 UTC).
    new_rows = (
        await db.execute(
            text(f"""
                WITH mx AS (
                    SELECT (max(time) AT TIME ZONE 'America/New_York')::date AS d,
                           (max(time) AT TIME ZONE 'America/New_York')::time AS t
                    FROM market_data_1min WHERE ticker = :sym
                ),
                settled AS (
                    SELECT CASE WHEN t >= time '16:00' THEN d ELSE d - 1 END AS through FROM mx
                )
                SELECT max(time_bucket('30 minutes', time))     AS ts,
                       first(open, time)                        AS open,
                       max(high)                                AS high,
                       min(low)                                 AS low,
                       last(close, time)                        AS close,
                       sum(volume)                              AS volume,
                       count(DISTINCT time_bucket('30 minutes', time)) AS rth_bars
                FROM market_data_1min, settled
                WHERE ticker = :sym
                  AND (time AT TIME ZONE 'America/New_York')::date > :last_date
                  AND (time AT TIME ZONE 'America/New_York')::date <= settled.through
                  AND {_RTH_FILTER}
                GROUP BY (time AT TIME ZONE 'America/New_York')::date
                ORDER BY ts
            """),
            {"sym": symbol, "last_date": last_date},
        )
    ).mappings().all()
    if not new_rows:
        return 0

    # Warmup from existing daily bars so sma_200 / ret_252d are exact for the new rows.
    warm = (
        await db.execute(
            text("""
                SELECT ts, adj_open AS open, adj_high AS high, adj_low AS low,
                       adj_close AS close, adj_volume AS volume
                FROM bars_1d WHERE instrument_id = :iid
                ORDER BY ts DESC LIMIT :lim
            """),
            {"iid": iid, "lim": _WARMUP_1D_ROWS},
        )
    ).mappings().all()

    warm_df = pd.DataFrame(warm[::-1]) if warm else pd.DataFrame(
        columns=["ts", "open", "high", "low", "close", "volume"]
    )
    new_df = pd.DataFrame(new_rows)
    df = pd.concat([warm_df[["ts", "open", "high", "low", "close", "volume"]], new_df], ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype("float64")

    block = common_indicator_block(df["close"], df["high"], df["low"], df["volume"])
    for k, s in block.items():
        df[k] = s.to_numpy()
    prev_close = df["close"].shift(1)
    for h in _DAY_RETURN_HORIZONS:
        df[f"ret_{h}d"] = df["close"].pct_change(h)
    df["gap_overnight"] = df["open"] / prev_close - 1.0

    rth_by_ts = {pd.Timestamp(r["ts"]): int(r["rth_bars"]) for r in new_rows}
    new = df[df["ts"].isin(rth_by_ts.keys())]
    if new.empty:
        return 0

    sql = text(_upsert_sql("bars_1d", _1D_INSERT_COLS))
    params = []
    for r in new.itertuples(index=False):
        d = r._asdict()
        ts = d["ts"].to_pydatetime()
        rec = {
            "ts": ts, "instrument_id": iid,
            "rth_bars": rth_by_ts.get(d["ts"]),
            "raw_close": _clean(d["close"]),
            "adj_open": _clean(d["open"]), "adj_high": _clean(d["high"]),
            "adj_low": _clean(d["low"]), "adj_close": _clean(d["close"]),
            "adj_volume": int(d["volume"]),
        }
        for col in _1D_INSERT_COLS:
            if col not in rec:
                rec[col] = _clean(d[col])
        params.append(rec)

    await db.execute(sql, params)
    return len(params)


# ---------------------------------------------------------------------------
# Massive fallback (symbols with no 1-min coverage)
# ---------------------------------------------------------------------------


async def _massive_fallback(db, symbol: str, iid: int, stop: threading.Event) -> tuple[int, int]:
    """Catch up a non-streamed symbol from the Massive REST API (OHLCV only).

    Reuses seed_market_data's fetch/write helpers. Indicators are left for the next
    full import; this only keeps charts and the change_pct baseline current.
    """
    import os

    api_key = os.getenv("MASSIVE_API_KEY", "")
    if not api_key:
        return 0, 0
    base_url = os.getenv("MASSIVE_BASE_URL", "https://api.massive.com")

    import httpx

    from app.core.seed_market_data import _fetch_and_write_1d, _fetch_and_write_30m

    if stop.is_set():
        return 0, 0
    # Short catch-up window: just enough to close the typical few-day gap (the
    # symbol's bulk history is already loaded from parquet). OHLCV only.
    today = date.today()
    from_30m = (today - timedelta(days=20)).isoformat()
    from_1d = (today - timedelta(days=20)).isoformat()
    to = today.isoformat()
    n30 = n1d = 0
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {api_key}"}, timeout=30.0
    ) as client:
        try:
            n30 = await _fetch_and_write_30m(client, db, api_key, base_url, symbol, iid, from_30m, to)
        except Exception:
            logger.warning("freshness: Massive 30m fetch failed for %s", symbol, exc_info=True)
        try:
            n1d = await _fetch_and_write_1d(client, db, api_key, base_url, symbol, iid, from_1d, to)
        except Exception:
            logger.warning("freshness: Massive daily fetch failed for %s", symbol, exc_info=True)
    return n30, n1d


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def _is_stale(db, iid: int) -> bool:
    """True when bars_30m has no rows or its latest bar is more than ~2 days old —
    the gate for the (costly) Massive fallback so fresh symbols aren't re-fetched."""
    last = (
        await db.execute(
            text("SELECT max(ts) FROM bars_30m WHERE instrument_id = :iid"), {"iid": iid}
        )
    ).scalar()
    if last is None:
        return True
    return last < datetime.now(last.tzinfo) - timedelta(days=2)


async def check_and_backfill_once(stop: threading.Event) -> dict:
    tickers = _get_seed_tickers()
    factory, engine = _make_session()
    bars_30m = bars_1d = massive = 0
    updated: list[str] = []
    checked = 0
    try:
        for sym in tickers:
            if stop.is_set():
                break
            n30 = n1d = 0
            try:
                async with factory() as db:
                    iid = await _ensure_instrument(db, sym, _asset_type(sym))
                    has_1min = (
                        await db.execute(
                            text("SELECT EXISTS(SELECT 1 FROM market_data_1min WHERE ticker = :s)"),
                            {"s": sym},
                        )
                    ).scalar()

                    if has_1min:
                        # 30-min and daily commit independently so one failing never
                        # rolls back the other.
                        try:
                            n30 = await _backfill_30m(db, sym, iid)
                            await db.commit()
                        except Exception:
                            await db.rollback()
                            logger.warning("freshness: 30m backfill failed for %s", sym, exc_info=True)
                        try:
                            n1d = await _backfill_1d(db, sym, iid)
                            await db.commit()
                        except Exception:
                            await db.rollback()
                            logger.warning("freshness: daily backfill failed for %s", sym, exc_info=True)
                    elif await _is_stale(db, iid):
                        n30, n1d = await _massive_fallback(db, sym, iid, stop)
                        await db.commit()
                        if n30 or n1d:
                            massive += 1
                checked += 1
                bars_30m += n30
                bars_1d += n1d
                if n30 or n1d:
                    updated.append(sym)
            except Exception:
                logger.warning("freshness: backfill failed for %s", sym, exc_info=True)
    finally:
        await engine.dispose()

    logger.info(
        "freshness: checked %d symbols, +%d 30-min bars, +%d daily bars%s (updated: %s)",
        checked, bars_30m, bars_1d,
        f", {massive} via Massive" if massive else "",
        ", ".join(updated) if updated else "none — all fresh",
    )
    return {
        "checked": checked, "bars_30m": bars_30m, "bars_1d": bars_1d,
        "massive": massive, "updated": updated,
    }


# ---------------------------------------------------------------------------
# Scheduler (startup check + daily after-close run) — lifespan-thread pattern
# ---------------------------------------------------------------------------

_DAILY_HOUR_ET = 18  # 18:30 ET ≈ after close, so the latest session has settled
_DAILY_MIN_ET = 30


def run_freshness_scheduler(stop_event: threading.Event) -> None:
    """Background thread: check once on startup, then daily at 18:30 ET."""
    if not settings.FRESHNESS_ENABLED:
        logger.info("freshness: disabled via FRESHNESS_ENABLED=false")
        return

    logger.info("freshness: initial check on startup")
    try:
        asyncio.run(check_and_backfill_once(stop_event))
    except Exception:
        logger.warning("freshness: startup check failed", exc_info=True)

    while not stop_event.is_set():
        now_et = datetime.now(ET)
        target = now_et.replace(hour=_DAILY_HOUR_ET, minute=_DAILY_MIN_ET, second=0, microsecond=0)
        if target <= now_et:
            target += timedelta(days=1)
        wait_secs = (target - now_et).total_seconds()
        logger.info(
            "freshness: next check at %s ET (%.1fh)",
            target.strftime("%Y-%m-%d %H:%M"), wait_secs / 3600,
        )
        if stop_event.wait(timeout=wait_secs):
            break
        try:
            asyncio.run(check_and_backfill_once(stop_event))
        except Exception:
            logger.warning("freshness: daily check failed", exc_info=True)
