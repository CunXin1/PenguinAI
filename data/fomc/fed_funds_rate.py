"""Federal funds rate target history — hardcoded lookup table.

Every FOMC rate *change* from 2000-01-01 through present (June 2026).
Only dates where the target rate (pre-2008) or target range (post-2008)
actually changed are included — meetings that held rates steady are omitted.

Sources (cross-verified):
  - Federal Reserve official press releases (federalreserve.gov)
  - FRED: DFEDTARU / DFEDTARL series (fred.stlouisfed.org)
  - fedprimerate.com historical table
  - Bankrate federal funds rate history

Format: ``{date_str: (lower_pct, upper_pct)}``

Pre-December 2008 the Fed set a single target rate, not a range.
For consistency the single target is stored as ``(rate, rate)``
so all entries are 2-tuples.

Usage::

    from data.fomc.fed_funds_rate import FED_FUNDS_RATE_HISTORY, get_rate_on_date

    # Direct lookup
    rate = FED_FUNDS_RATE_HISTORY["2022-03-16"]  # (0.25, 0.50)

    # Get effective rate for any calendar date
    low, high = get_rate_on_date("2023-06-01")   # (5.00, 5.25)
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date

# ─── Single-target era (pre-Dec 2008): stored as (rate, rate) ────────────────
# ─── Target-range era (Dec 2008 onward): stored as (lower, upper) ────────────
#
# NOTE: The rate *before* the first entry (i.e. before 2000-02-02) was 5.50%,
# set on 1999-11-16.  We include it as the "initial state" sentinel so that
# get_rate_on_date() works for any date from 2000-01-01 onward.

FED_FUNDS_RATE_HISTORY: dict[str, tuple[float, float]] = {
    # ── Pre-2000 anchor (rate inherited into 2000) ───────────────────────────
    "1999-11-16": (5.50, 5.50),
    # ── 2000: Greenspan tightening cycle (3 hikes) ──────────────────────────
    "2000-02-02": (5.75, 5.75),
    "2000-03-21": (6.00, 6.00),
    "2000-05-16": (6.50, 6.50),  # cycle peak
    # ── 2001: Dot-com bust + 9/11 (11 cuts) ─────────────────────────────────
    "2001-01-03": (6.00, 6.00),  # emergency inter-meeting cut
    "2001-01-31": (5.50, 5.50),
    "2001-03-20": (5.00, 5.00),
    "2001-04-18": (4.50, 4.50),
    "2001-05-15": (4.00, 4.00),
    "2001-06-27": (3.75, 3.75),
    "2001-08-21": (3.50, 3.50),
    "2001-09-17": (3.00, 3.00),  # emergency cut post-9/11
    "2001-10-02": (2.50, 2.50),
    "2001-11-06": (2.00, 2.00),
    "2001-12-11": (1.75, 1.75),
    # ── 2002: one more cut ───────────────────────────────────────────────────
    "2002-11-06": (1.25, 1.25),
    # ── 2003: final cut of easing cycle ──────────────────────────────────────
    "2003-06-25": (1.00, 1.00),  # cycle trough
    # ── 2004–2006: Greenspan/Bernanke tightening (17 consecutive 25bp hikes) ─
    "2004-06-30": (1.25, 1.25),
    "2004-08-10": (1.50, 1.50),
    "2004-09-21": (1.75, 1.75),
    "2004-11-10": (2.00, 2.00),
    "2004-12-14": (2.25, 2.25),
    "2005-02-02": (2.50, 2.50),
    "2005-03-22": (2.75, 2.75),
    "2005-05-03": (3.00, 3.00),
    "2005-06-30": (3.25, 3.25),
    "2005-08-09": (3.50, 3.50),
    "2005-09-20": (3.75, 3.75),
    "2005-11-01": (4.00, 4.00),
    "2005-12-13": (4.25, 4.25),
    "2006-01-31": (4.50, 4.50),
    "2006-03-28": (4.75, 4.75),
    "2006-05-10": (5.00, 5.00),
    "2006-06-29": (5.25, 5.25),  # cycle peak
    # ── 2007–2008: Financial crisis easing (10 cuts) ────────────────────────
    "2007-09-18": (4.75, 4.75),
    "2007-10-31": (4.50, 4.50),
    "2007-12-11": (4.25, 4.25),
    "2008-01-22": (3.50, 3.50),  # emergency inter-meeting cut (75bp)
    "2008-01-30": (3.00, 3.00),
    "2008-03-18": (2.25, 2.25),  # 75bp cut
    "2008-04-30": (2.00, 2.00),
    "2008-10-08": (1.50, 1.50),  # emergency inter-meeting cut
    "2008-10-29": (1.00, 1.00),
    # ── Switch to target RANGE ───────────────────────────────────────────────
    "2008-12-16": (0.00, 0.25),  # ZIRP begins — held until Dec 2015
    # ── 2015–2018: Post-GFC normalization (9 hikes) ─────────────────────────
    "2015-12-16": (0.25, 0.50),  # first hike in 7 years
    "2016-12-14": (0.50, 0.75),
    "2017-03-15": (0.75, 1.00),
    "2017-06-14": (1.00, 1.25),
    "2017-12-13": (1.25, 1.50),
    "2018-03-21": (1.50, 1.75),
    "2018-06-13": (1.75, 2.00),
    "2018-09-26": (2.00, 2.25),
    "2018-12-19": (2.25, 2.50),  # cycle peak
    # ── 2019: "Mid-cycle adjustment" cuts (3 cuts) ──────────────────────────
    "2019-07-31": (2.00, 2.25),
    "2019-09-18": (1.75, 2.00),
    "2019-10-30": (1.50, 1.75),
    # ── 2020: COVID-19 emergency cuts ────────────────────────────────────────
    "2020-03-03": (1.00, 1.25),  # emergency inter-meeting cut (50bp)
    "2020-03-15": (0.00, 0.25),  # emergency Sunday cut — back to ZIRP
    # ── 2022–2023: Inflation-fighting tightening (11 hikes) ─────────────────
    "2022-03-16": (0.25, 0.50),
    "2022-05-04": (0.75, 1.00),
    "2022-06-15": (1.50, 1.75),  # 75bp
    "2022-07-27": (2.25, 2.50),  # 75bp
    "2022-09-21": (3.00, 3.25),  # 75bp
    "2022-11-02": (3.75, 4.00),  # 75bp
    "2022-12-14": (4.25, 4.50),  # 50bp step-down
    "2023-02-01": (4.50, 4.75),
    "2023-03-22": (4.75, 5.00),
    "2023-05-03": (5.00, 5.25),
    "2023-07-26": (5.25, 5.50),  # cycle peak — held 14 months
    # ── 2024: Easing begins (3 cuts) ────────────────────────────────────────
    "2024-09-18": (4.75, 5.00),  # first cut in 4+ years (50bp)
    "2024-11-07": (4.50, 4.75),
    "2024-12-18": (4.25, 4.50),
    # ── 2025: Continued easing (3 cuts, Sep–Dec) ────────────────────────────
    # Jan, Mar, May, Jun, Jul 2025 meetings all held steady at 4.25-4.50
    "2025-09-17": (4.00, 4.25),
    "2025-10-29": (3.75, 4.00),
    "2025-12-10": (3.50, 3.75),  # current rate as of June 2026
    # ── 2026: No changes yet ─────────────────────────────────────────────────
    # Jan 28, Mar 18, Apr 29 meetings all held steady at 3.50-3.75
    # Next meeting: Jun 17, 2026 (expected hold)
}

# Sorted list for binary-search lookups
_SORTED_DATES: list[date] = sorted(
    date.fromisoformat(d) for d in FED_FUNDS_RATE_HISTORY
)
_SORTED_RATES: list[tuple[float, float]] = [
    FED_FUNDS_RATE_HISTORY[d.isoformat()] for d in _SORTED_DATES
]


def get_rate_on_date(query: str | date) -> tuple[float, float]:
    """Return the effective (lower, upper) target range on any given date.

    Uses binary search to find the most recent rate change on or before
    the query date.

    Parameters
    ----------
    query : str or date
        ISO-format date string (``"2023-06-15"``) or a ``datetime.date``.

    Returns
    -------
    tuple[float, float]
        ``(lower_bound_pct, upper_bound_pct)``.  For the single-target era
        both values are identical.

    Raises
    ------
    ValueError
        If the query date is before the earliest entry in the table.
    """
    if isinstance(query, str):
        query = date.fromisoformat(query)

    idx = bisect_right(_SORTED_DATES, query) - 1
    if idx < 0:
        raise ValueError(
            f"Date {query} is before the earliest rate entry ({_SORTED_DATES[0]})"
        )
    return _SORTED_RATES[idx]


def get_rate_changes_in_range(
    start: str | date,
    end: str | date,
) -> list[tuple[str, tuple[float, float]]]:
    """Return all rate changes between start and end (inclusive).

    Returns
    -------
    list of (date_str, (lower, upper)) tuples, chronologically ordered.
    """
    if isinstance(start, str):
        start = date.fromisoformat(start)
    if isinstance(end, str):
        end = date.fromisoformat(end)

    results = []
    for d, r in zip(_SORTED_DATES, _SORTED_RATES):
        if d < start:
            continue
        if d > end:
            break
        results.append((d.isoformat(), r))
    return results


if __name__ == "__main__":
    print(f"Total rate changes in table: {len(FED_FUNDS_RATE_HISTORY)}")
    print()

    # Print full history
    for d in _SORTED_DATES:
        low, high = FED_FUNDS_RATE_HISTORY[d.isoformat()]
        if low == high:
            print(f"  {d}  →  {low:.2f}%")
        else:
            print(f"  {d}  →  {low:.2f}% – {high:.2f}%")

    print()

    # Demo: what was the rate on a specific date?
    for test_date in ["2001-09-12", "2008-12-31", "2020-04-01", "2023-08-15", "2026-06-01"]:
        low, high = get_rate_on_date(test_date)
        if low == high:
            print(f"  Rate on {test_date}: {low:.2f}%")
        else:
            print(f"  Rate on {test_date}: {low:.2f}% – {high:.2f}%")
