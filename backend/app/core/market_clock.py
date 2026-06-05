"""Single source of truth for "is the US market open right now?".

Combines a clock-based regular-session check (ET weekday 09:30–16:00) with a
clock-INDEPENDENT fallback: if the live minute feed's newest bar is actually
advancing in real (monotonic) time, the market is live regardless of the wall
clock. Shared by the /market-data/status endpoint and the heatmap so every
surface agrees on ONE answer. Holidays are not modeled.
"""

from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ET = ZoneInfo("America/New_York")  # US market session timezone


def is_regular_session(now_utc: datetime) -> bool:
    """US regular session: weekdays 09:30–16:00 ET (holidays not modeled)."""
    et = now_utc.astimezone(ET)
    if et.weekday() >= 5:  # Sat/Sun
        return False
    open_t = et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = et.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= et < close_t


# Tracks whether the live minute feed is advancing, using a MONOTONIC clock so it
# works even if the system wall-clock is wrong. Process-global (one API worker).
_LIVE_TICKS: dict = {"max": None, "advanced_at": None}
# Stay "live" if a new bar arrived within this many real seconds. Bars land ~1/min
# during a session (with jitter / 15-min Massive delay), so a generous window keeps
# the badge stable; it flips to closed only after the feed truly stops (~6 min).
_LIVE_WINDOW_S = 360.0


def ticks_advancing(latest_tick: datetime | None) -> bool:
    """True if the newest minute bar grew within the last _LIVE_WINDOW_S seconds.

    Robust to a wrong system clock: it requires an actual *advance* between
    observations, not just recency vs a (possibly-bad) now(), so stale data can't
    fool it either. Process-global state — safe to call from multiple endpoints;
    every caller just contributes another observation.
    """
    if latest_tick is None:
        return False
    mono = monotonic()
    prev = _LIVE_TICKS["max"]
    if prev is None:
        _LIVE_TICKS["max"] = latest_tick  # seed (can't tell on first observation)
    elif latest_tick > prev:
        _LIVE_TICKS["max"] = latest_tick
        _LIVE_TICKS["advanced_at"] = mono
    at = _LIVE_TICKS["advanced_at"]
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
