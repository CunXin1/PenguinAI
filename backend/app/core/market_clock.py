"""Single source of truth for "is the US market open right now?".

Combines exchange_calendars (authoritative NYSE schedule including holidays,
early closes, and special sessions) with a clock-INDEPENDENT fallback: if the
live minute feed's newest bar is actually advancing in real (monotonic) time,
the market is live regardless of the wall clock. Shared by the /market-data/status
endpoint and the heatmap so every surface agrees on ONE answer.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from datetime import time as dtime
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


def next_session_open(now_utc: datetime | None = None) -> datetime | None:
    """Next US equity PRE-MARKET open (04:00 ET, UTC-returned), strictly after ``now``.

    Holiday- and weekend-aware via exchange_calendars: we take the next regular
    session's date and pin it to 04:00 ET — the moment pre-market trading (and
    our live feed) actually resumes — rather than the 09:30 regular open. So on a
    Friday/weekend it returns Monday 04:00 ET (or the next trading day if Monday
    is a holiday). Returns None if the calendar can't resolve it.
    """
    now = now_utc or datetime.now(UTC)
    try:
        reg_open = _nyse.next_open(pd.Timestamp(now))  # next regular open, tz-aware UTC
    except (ValueError, KeyError):
        return None
    session_date = reg_open.tz_convert(ET).date()
    premarket = datetime.combine(session_date, dtime(4, 0), tzinfo=ET)
    return premarket.astimezone(UTC)


_LIVE_WINDOW_S = 360.0


def ticks_advancing(latest_tick: datetime | None) -> bool:
    """True if the newest minute bar is recent — i.e. the live feed is flowing.

    STATELESS: compares the bar's own timestamp to wall-clock now, so the answer
    depends only on the DB row, not on per-process memory. Two consequences that
    fix real bugs:
      - every uvicorn worker (WEB_CONCURRENCY=4) computes the SAME answer from the
        SAME ``max(time)`` row, so the LIVE/CLOSED badge can no longer flicker
        depending on which worker served ``/market-data/status``;
      - there is no cold-start blind spot — a fresh process reports "live"
        immediately if the latest bar is recent, instead of waiting for the next
        bar to print before it has a baseline.

    A feed that stalls stops advancing ``latest_tick``, so it ages out of the
    window naturally. Wall-clock dependence is acceptable: ``get_session_phase``
    already relies on the system clock, so this introduces no new assumption.
    """
    if latest_tick is None:
        return False
    now = datetime.now(latest_tick.tzinfo or UTC)
    return (now - latest_tick).total_seconds() <= _LIVE_WINDOW_S


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
    # When not active, surface the next regular open so the UI can show a
    # "reopens Mon 9:30 AM" hint instead of a bare "CLOSED".
    next_open = None if is_active else next_session_open(now)
    return {
        "market_open": session_open or advancing,
        "market_active": is_active,
        "session_phase": phase,
        "session_open": session_open,
        # Is the live minute feed actually flowing? During a regular session this
        # is normally true; if both real-time sources die mid-session it goes false
        # while `session_open` stays true — that gap is what the frontend renders as
        # a "DELAYED" badge instead of a misleading green "LIVE".
        "feed_live": advancing,
        "source": "session" if session_open else ("ticks" if advancing else phase.lower()),
        "as_of": now.isoformat(),
        "latest_tick": latest.isoformat() if latest is not None else None,
        "next_open": next_open.isoformat() if next_open is not None else None,
    }
