"""After-close + after-hours intraday-bar refresh (30-min AND 10-min).

At ~16:05 and ~20:05 ET on weekdays, pull today's bars from Massive (raw via
adjusted=false, split-adjusted via adjusted=true), upsert into bars_30m AND
bars_10m, recompute indicators over a recent window, and fall back to Yahoo if
Massive returns nothing (30-min only — yfinance has no 10-min interval). Keeps
both intraday tables current with the just-closed session for the watched
universe. bars_10m backs the 1W chart range, which otherwise would not see the
current session until the nightly freshness backfill at 18:30 ET.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from sqlalchemy import text

from data.ingestion.realtime.indicators import _IND_COLS, _compute

logger = logging.getLogger("realtime.close30m")
ET = ZoneInfo("America/New_York")
_RUN_HOURS = (16, 20)  # ET hours to run (close + post-market close), minute :05

_INSTR_SQL = text(
    "SELECT instrument_id FROM instruments WHERE symbol = :s ORDER BY instrument_id LIMIT 1"
)


def _build_sql(table: str) -> tuple:
    """(recent, upsert, ind_update) SQL for a bars_30m / bars_10m table — both share
    the identical column layout, so the only difference is the table name."""
    recent = text(
        f"SELECT ts AS time, adj_open AS open, adj_high AS high, adj_low AS low, "
        f"adj_close AS close, adj_volume AS volume FROM {table} "
        f"WHERE instrument_id = :iid ORDER BY ts DESC LIMIT 400"
    )
    upsert = text(
        f"""
        INSERT INTO {table} (ts, instrument_id, rth,
            raw_open, raw_high, raw_low, raw_close, raw_volume,
            adj_open, adj_high, adj_low, adj_close, adj_volume)
        VALUES (:ts, :iid, :rth,
            :raw_open, :raw_high, :raw_low, :raw_close, :raw_volume,
            :adj_open, :adj_high, :adj_low, :adj_close, :adj_volume)
        ON CONFLICT (ts, instrument_id) DO UPDATE SET
            rth = EXCLUDED.rth,
            raw_open = EXCLUDED.raw_open, raw_high = EXCLUDED.raw_high,
            raw_low = EXCLUDED.raw_low, raw_close = EXCLUDED.raw_close,
            raw_volume = EXCLUDED.raw_volume,
            adj_open = EXCLUDED.adj_open, adj_high = EXCLUDED.adj_high,
            adj_low = EXCLUDED.adj_low, adj_close = EXCLUDED.adj_close,
            adj_volume = EXCLUDED.adj_volume, updated_at = now()
        """
    )
    ind_update = text(
        f"UPDATE {table} SET "
        + ", ".join(f"{c} = :{c}" for c in _IND_COLS if c != "rth")
        + " WHERE instrument_id = :iid AND ts = :ts"
    )
    return recent, upsert, ind_update


# (table, bucket-minutes, yahoo-interval | None). bars_10m has no Yahoo fallback —
# yfinance offers no 10-minute interval, so it is Massive-only.
_TABLES = (
    ("bars_30m", 30, "30m"),
    ("bars_10m", 10, None),
)
_SQL = {table: _build_sql(table) for table, _, _ in _TABLES}


def _rth(ts_utc: datetime) -> bool:
    et = ts_utc.astimezone(ET)
    m = et.hour * 60 + et.minute
    return 9 * 60 + 30 <= m < 16 * 60


async def _massive_agg(client, base, key, sym, day, mult: int) -> dict[int, dict]:
    """{t_ms: {raw/adj OHLCV}} for `mult`-minute bars, merging adjusted=false (raw)
    + adjusted=true (adj)."""
    # Trailing range (not single {day}/{day}): a no-data current day 403s; a few
    # days back always spans the latest session. ON CONFLICT dedupes re-fetched days.
    frm = (datetime.fromisoformat(day).date() - timedelta(days=3)).isoformat()
    out: dict[int, dict] = {}
    for adjusted, pfx in (("false", "raw"), ("true", "adj")):
        url = (
            f"{base}/v2/aggs/ticker/{sym}/range/{mult}/minute/{frm}/{day}"
            f"?adjusted={adjusted}&sort=asc&limit=50000&apiKey={key}"
        )
        try:
            resp = await client.get(url)
        except httpx.HTTPError:
            continue
        if resp.status_code != 200:
            continue
        for b in (resp.json() or {}).get("results") or []:
            t = b.get("t")
            o, h, low, c = b.get("o"), b.get("h"), b.get("l"), b.get("c")
            if t is None or None in (o, h, low, c):
                continue
            row = out.setdefault(int(t), {})
            row[f"{pfx}_open"], row[f"{pfx}_high"] = o, h
            row[f"{pfx}_low"], row[f"{pfx}_close"] = low, c
            row[f"{pfx}_volume"] = int(round(float(b.get("v") or 0)))
    return out


def _yahoo_30m(sym: str) -> dict[int, dict]:
    """Fallback: today's 30-min bars via yfinance (raw OHLC + adj via Adj Close)."""
    try:
        import yfinance as yf
    except ModuleNotFoundError:
        return {}
    y = sym.replace(".", "-")
    df = yf.download(y, period="1d", interval="30m", prepost=True, auto_adjust=False, progress=False)
    if df is None or df.empty:
        return {}
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    out: dict[int, dict] = {}
    for idx, r in df.iterrows():
        ts = idx.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=ET)
        t_ms = int(ts.astimezone(UTC).timestamp() * 1000)
        close = float(r["Close"])
        adj_close = float(r.get("Adj Close", close))
        f = adj_close / close if close else 1.0
        vol = int(r["Volume"]) if not pd.isna(r["Volume"]) else 0
        out[t_ms] = {
            "raw_open": float(r["Open"]), "raw_high": float(r["High"]),
            "raw_low": float(r["Low"]), "raw_close": close, "raw_volume": vol,
            "adj_open": float(r["Open"]) * f, "adj_high": float(r["High"]) * f,
            "adj_low": float(r["Low"]) * f, "adj_close": adj_close, "adj_volume": vol,
        }
    return out


async def _refresh_indicators(engine, iid: int, recent_sql, ind_sql) -> None:
    async with engine.connect() as conn:
        rows = (await conn.execute(recent_sql, {"iid": iid})).mappings().all()
    if len(rows) < 2:
        return
    df = pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype("float64")
    out = await asyncio.to_thread(_compute, df)
    params = []
    for row in out.tail(20).itertuples(index=False):
        d = row._asdict()
        rec = {"iid": iid, "ts": d["time"].to_pydatetime()}
        for c in _IND_COLS:
            if c == "rth":
                continue
            v = d[c]
            rec[c] = None if v is None or (isinstance(v, float) and v != v) else float(v)
        params.append(rec)
    if params:
        async with engine.begin() as conn:
            await conn.execute(ind_sql, params)


async def _refresh_table(engine, client, base, key, sym, day, iid, table, mult, yf_interval) -> int:
    recent_sql, upsert_sql, ind_sql = _SQL[table]
    bars = await _massive_agg(client, base, key, sym, day, mult)
    if not bars and yf_interval:
        bars = await asyncio.to_thread(_yahoo_30m, sym)  # 30m-only fallback
    rows = []
    for t_ms, v in sorted(bars.items()):
        ts = datetime.fromtimestamp(t_ms / 1000.0, tz=UTC)
        raw_c = v.get("raw_close")
        rows.append(
            {
                "ts": ts, "iid": iid, "rth": _rth(ts),
                "raw_open": v.get("raw_open"), "raw_high": v.get("raw_high"),
                "raw_low": v.get("raw_low"), "raw_close": raw_c,
                "raw_volume": v.get("raw_volume"),
                "adj_open": v.get("adj_open", v.get("raw_open")),
                "adj_high": v.get("adj_high", v.get("raw_high")),
                "adj_low": v.get("adj_low", v.get("raw_low")),
                "adj_close": v.get("adj_close", raw_c),
                "adj_volume": v.get("adj_volume", v.get("raw_volume")),
            }
        )
    if not rows:
        return 0
    async with engine.begin() as conn:
        await conn.execute(upsert_sql, rows)
    await _refresh_indicators(engine, iid, recent_sql, ind_sql)
    return len(rows)


async def refresh_symbol(engine, client, base, key, sym: str, day: str) -> int:
    async with engine.connect() as conn:
        iid = (await conn.execute(_INSTR_SQL, {"s": sym})).scalar()
    if iid is None:
        return 0
    total = 0
    for table, mult, yf_interval in _TABLES:
        try:
            total += await _refresh_table(
                engine, client, base, key, sym, day, iid, table, mult, yf_interval
            )
        except Exception as exc:  # noqa: BLE001 — one table failing must not skip the other
            logger.error("%s refresh %s: %r", table, sym, exc)
    return total


async def run_once(engine, settings, symbols: list[str]) -> int:
    if not settings.MASSIVE_API_KEY:
        logger.warning("MASSIVE_API_KEY empty — 30m refresh uses Yahoo only")
    base = settings.MASSIVE_BASE_URL.rstrip("/")
    key = settings.MASSIVE_API_KEY
    day = datetime.now(ET).date().isoformat()
    sem = asyncio.Semaphore(6)
    total = 0
    async with httpx.AsyncClient(
        timeout=40.0, headers={"Authorization": f"Bearer {key}"} if key else {}
    ) as client:
        async def one(s):
            async with sem:
                try:
                    return await refresh_symbol(engine, client, base, key, s, day)
                except Exception as exc:  # noqa: BLE001
                    logger.error("30m refresh %s: %r", s, exc)
                    return 0
        total = sum(await asyncio.gather(*(one(s) for s in symbols)))
    logger.info(
        "intraday refresh (%s): %d bars (30m+10m) across %d symbols", day, total, len(symbols)
    )
    return total


def _next_run_delay(now_et: datetime) -> float:
    """Seconds until the next :05 of an _RUN_HOURS hour, ET, weekdays."""
    candidates = []
    for d in range(0, 5):
        day = (now_et + timedelta(days=d)).date()
        for hr in _RUN_HOURS:
            cand = datetime.combine(day, datetime.min.time(), tzinfo=ET).replace(hour=hr, minute=5)
            if cand > now_et and cand.weekday() < 5:
                candidates.append(cand)
    return (min(candidates) - now_et).total_seconds() if candidates else 3600.0


async def run(engine, settings, stop, symbols_fn) -> None:
    """Sleep until the next scheduled ET slot, then refresh. symbols_fn() returns
    the watched symbols at run time."""
    logger.info("intraday (30m+10m) close refresh scheduler up (runs %s:05 ET weekdays)", _RUN_HOURS)
    while not stop.is_set():
        delay = _next_run_delay(datetime.now(ET))
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            return  # stopped
        except TimeoutError:
            pass
        try:
            await run_once(engine, settings, await symbols_fn())
        except Exception as exc:  # noqa: BLE001
            logger.error("30m refresh run failed: %r", exc)
