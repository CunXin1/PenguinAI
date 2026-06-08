"""Single source of truth for "is the US market open right now?".

Combines exchange_calendars (authoritative NYSE schedule including holidays,
early closes, and special sessions) with a clock-INDEPENDENT fallback: if the
live minute feed's newest bar is actually advancing in real (monotonic) time,
the market is live regardless of the wall clock. Shared by the /market-data/status
endpoint and the heatmap so every surface agrees on ONE answer.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from time import monotonic
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

_nyse = xcals.get_calendar("XNYS")


def is_regular_session(now_utc: datetime) -> bool:
    """True when `now_utc` falls inside an NYSE regular trading session,
    respecting all holidays, early closes, and special sessions."""
    ts = pd.Timestamp(now_utc, tz="UTC") if now_utc.tzinfo is None else pd.Timestamp(now_utc).tz_convert("UTC")
    if not _nyse.is_session(ts.normalize().tz_localize(None)):
        return False
    try:
        open_t = _nyse.session_open(ts.normalize().tz_localize(None))
        close_t = _nyse.session_close(ts.normalize().tz_localize(None))
    except ValueError:
        return False
    return open_t <= ts <= close_t


def is_early_close(d: datetime) -> bool:
    """True if the given date is an NYSE early-close session."""
    ts = pd.Timestamp(d, tz="UTC") if d.tzinfo is None else pd.Timestamp(d).tz_convert("UTC")
    ts_naive = ts.normalize().tz_localize(None)
    if not _nyse.is_session(ts_naive):
        return False
    close_t = _nyse.session_close(ts_naive)
    return close_t.hour < 16


_LIVE_WINDOW_S = 360.0
_tick_lock = threading.Lock()


class _TickState:
    __slots__ = ("max_tick", "advanced_at")

    def __init__(self):
        self.max_tick: datetime | None = None
        self.advanced_at: float | None = None


_tick_state = _TickState()


def ticks_advancing(latest_tick: datetime | None) -> bool:
    """True if the newest minute bar grew within the last _LIVE_WINDOW_S seconds.

    Thread-safe: uses a lock to ensure atomic read-modify-write of the shared state.
    """
    if latest_tick is None:
        return False
    mono = monotonic()
    with _tick_lock:
        if _tick_state.max_tick is None:
            _tick_state.max_tick = latest_tick
        elif latest_tick > _tick_state.max_tick:
            _tick_state.max_tick = latest_tick
            _tick_state.advanced_at = mono
        at = _tick_state.advanced_at
    return at is not None and (mono - at) <= _LIVE_WINDOW_S


async def get_market_status(db: AsyncSession) -> dict:
    """The one answer every surface uses for "is the market open".

    ``market_open`` is true when EITHER the ET clock says we're in the regular
    session OR the live feed is actively advancing (covers a live pre/post feed
    and is robust to a wrong system clock). ``source`` says which path decided it.
    """
    now = datetime.now(UTC)
    session_open = is_regular_session(now)
    latest = (await db.execute(text("SELECT max(time) FROM market_data_1min"))).scalar()
    advancing = ticks_advancing(latest)
    is_open = session_open or advancing
    return {
        "market_open": is_open,
        "session_open": session_open,
        "source": "session" if session_open else ("ticks" if advancing else "closed"),
        "as_of": now.isoformat(),
        "latest_tick": latest.isoformat() if latest is not None else None,
    }
