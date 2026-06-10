"""Single source of truth for the FOMC meeting calendar.

Both the backend API (``app.api.routes.fomc``) and the data-layer scheduler
(``data.fomc.scheduler``) import ``FOMC_MEETINGS`` from here, so the two can
never drift. Dates are FOMC *decision* days (the second day of each two-day
meeting), ISO ``YYYY-MM-DD``, sorted ascending.

⚠️  UPDATE ANNUALLY: the Fed publishes the next year's schedule around mid-year.
Append the new dates before the list runs out — once ``today`` passes the last
entry, the countdown/schedule stop advancing and the scheduler's post-meeting
rate triggers no longer fire. ``meetings_need_update()`` flags when the tail is
near so the backend can warn on startup.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

FOMC_MEETINGS: list[str] = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-05-05", "2027-06-16",
    "2027-07-28", "2027-09-22", "2027-10-27", "2027-12-15",
]


def next_meeting_date(today: str | None = None) -> str | None:
    """First scheduled meeting on/after ``today`` (YYYY-MM-DD), or None if the
    calendar is exhausted."""
    today = today or datetime.now(UTC).strftime("%Y-%m-%d")
    for d in FOMC_MEETINGS:
        if d >= today:
            return d
    return None


def meetings_need_update(within_days: int = 90) -> bool:
    """True when the calendar is exhausted or its last entry is fewer than
    ``within_days`` away — a signal to append the Fed's newly-published schedule."""
    if not FOMC_MEETINGS:
        return True
    last = datetime.strptime(FOMC_MEETINGS[-1], "%Y-%m-%d").replace(tzinfo=UTC)
    return last - datetime.now(UTC) < timedelta(days=within_days)
