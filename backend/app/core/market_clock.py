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
    ts = (
        pd.Timestamp(now_utc, tz="UTC")
        if now_utc.tzinfo is None
        else pd.Timestamp(now_utc).tz_convert("UTC")
    )
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


def get_session_phase(now_utc: datetime | None = None) -> str:
    """Current US equity session phase (ET-based).

    PRE_MARKET:   04:00–09:30 ET on trading days
    REGULAR:      09:30–close ET (16:00, or earlier on early-close days)
    AFTER_HOURS:  close–close+4h ET
    OVERNIGHT:    remaining weekday hours (20:00–04:00 ET typical)
    CLOSED:       weekends and NYSE holidays
    """
    now = now_utc or datetime.now(UTC)
    et = now.astimezone(ET)
    m = et.hour * 60 + et.minute

    if et.weekday() >= 5:
        return "CLOSED"

    today_naive = pd.Timestamp(et.date())
    if not _nyse.is_session(today_naive):
        return "CLOSED"

    try:
        close_ts = _nyse.session_close(today_naive)
        close_et = close_ts.tz_convert(ET)
        close_m = close_et.hour * 60 + close_et.minute
    except (ValueError, KeyError):
        close_m = 16 * 60

    ah_end_m = close_m + 4 * 60

    if m < 4 * 60:
        return "OVERNIGHT"
    if m < 9 * 60 + 30:
        return "PRE_MARKET"
    if m < close_m:
        return "REGULAR"
    if m < ah_end_m:
        return "AFTER_HOURS"
    return "OVERNIGHT"


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
    """The one answer every surface uses for market state.

    ``market_open`` — backward compat: true during regular session OR ticks advancing.
    ``market_active`` — true during ANY session (pre/regular/after/overnight) OR ticks.
    ``session_phase`` — the specific phase label for the frontend.
    """
    now = datetime.now(UTC)
    phase = get_session_phase(now)
    session_open = phase == "REGULAR"
    latest = (await db.execute(text("SELECT max(time) FROM market_data_1min"))).scalar()
    advancing = ticks_advancing(latest)
    is_active = phase in ("PRE_MARKET", "REGULAR", "AFTER_HOURS") or advancing
    return {
        "market_open": session_open or advancing,
        "market_active": is_active,
        "session_phase": phase,
        "session_open": session_open,
        "source": "session" if session_open else ("ticks" if advancing else phase.lower()),
        "as_of": now.isoformat(),
        "latest_tick": latest.isoformat() if latest is not None else None,
    }
