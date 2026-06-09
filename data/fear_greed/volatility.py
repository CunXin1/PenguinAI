"""Multi-source VIX / VVIX orchestration with backup + cross-check.

Each symbol has a priority-ordered provider chain. We fetch from every
available provider, then:

  1. **Merge by day** in *ascending* priority — lower-priority sources fill in
     days the higher-priority source is missing (e.g. today, when CBOE lags),
     and higher-priority sources overwrite on shared days. So the authoritative
     source wins where it has data, and backups keep the tail fresh.
  2. **Cross-check** the latest close across the sources that returned data; a
     relative divergence above ``_DIVERGENCE`` is logged as a warning (possible
     bad data on one feed).
  3. If the primary fails entirely, the next source in the chain is used — "if
     one fails, use another".

Provider chains (priority high → low):
  VIX  : CBOE  →  Yahoo  →  FRED
  VVIX : CBOE  →  Yahoo
"""

from __future__ import annotations

import logging
from datetime import datetime

from .cboe import fetch_volatility as fetch_cboe
from .fred import fetch_fred_vix
from .yahoo import fetch_yahoo

logger = logging.getLogger(__name__)

_DIVERGENCE = 0.08  # 8% relative — flag suspected bad data on one source


def _latest(rows: list[dict]) -> tuple[datetime, float] | None:
    if not rows:
        return None
    r = max(rows, key=lambda x: x["time"])
    return r["time"], r["close"]


def _crosscheck(symbol: str, by_source: dict[str, list[dict]]) -> dict:
    """Compare the latest close across sources; log divergence. Returns a summary."""
    latto = {s: _latest(rows) for s, rows in by_source.items() if rows}
    closes = {s: v[1] for s, v in latto.items() if v}
    summary = {
        "symbol": symbol,
        "sources": {s: round(c, 2) for s, c in closes.items()},
        "agree": True,
    }
    if len(closes) >= 2:
        lo, hi = min(closes.values()), max(closes.values())
        if lo > 0 and (hi - lo) / lo > _DIVERGENCE:
            summary["agree"] = False
            logger.warning(
                "%s cross-check DIVERGENCE >%.0f%%: %s",
                symbol, _DIVERGENCE * 100,
                {s: round(c, 2) for s, c in closes.items()},
            )
        else:
            logger.info("%s cross-check ok: %s", symbol,
                        {s: round(c, 2) for s, c in closes.items()})
    return summary


def _merge_by_day(sources_low_to_high: list[list[dict]]) -> list[dict]:
    """Merge rows so higher-priority sources overwrite lower on shared days,
    while lower-priority sources fill days the higher source lacks."""
    by_day: dict[datetime, dict] = {}
    for rows in sources_low_to_high:  # apply low priority first
        for r in rows:
            by_day[r["time"]] = r
    return [by_day[d] for d in sorted(by_day)]


async def _gather(symbol: str, fred_key: str) -> dict[str, list[dict]]:
    """Run the provider chain for one symbol; returns {source: rows} (only successes)."""
    out: dict[str, list[dict]] = {}

    # CBOE (covers both symbols in one combined fetch — caller passes the slice).
    # Yahoo
    yrows = await fetch_yahoo(symbol)
    if yrows:
        out["yahoo"] = yrows

    if symbol == "VIX" and fred_key:
        frows = await fetch_fred_vix(fred_key)
        if frows:
            out["fred"] = frows
    return out


async def fetch_all_volatility(fred_key: str = "") -> dict:
    """Fetch + merge + cross-check VIX & VVIX across all sources.

    Returns ``{"rows": [...all merged rows...], "crosscheck": {symbol: summary}}``.
    """
    # CBOE returns VIX + VVIX together; split it once.
    cboe_rows = await fetch_cboe()
    cboe_by_symbol: dict[str, list[dict]] = {"VIX": [], "VVIX": []}
    for r in cboe_rows:
        cboe_by_symbol.setdefault(r["symbol"], []).append(r)

    merged: list[dict] = []
    crosscheck: dict[str, dict] = {}

    # Priority chains (high → low). CBOE is primary for both.
    chains = {
        "VIX": ["cboe", "yahoo", "fred"],
        "VVIX": ["cboe", "yahoo"],
    }

    for symbol, order in chains.items():
        by_source: dict[str, list[dict]] = {}
        if cboe_by_symbol.get(symbol):
            by_source["cboe"] = cboe_by_symbol[symbol]
        by_source.update(await _gather(symbol, fred_key))

        if not by_source:
            logger.warning("%s: all sources failed", symbol)
            crosscheck[symbol] = {"symbol": symbol, "sources": {}, "agree": False}
            continue

        crosscheck[symbol] = _crosscheck(symbol, by_source)

        # Merge in ascending priority (reverse of the high→low chain).
        ordered_low_to_high = [
            by_source[s] for s in reversed(order) if by_source.get(s)
        ]
        merged.extend(_merge_by_day(ordered_low_to_high))

    return {"rows": merged, "crosscheck": crosscheck}
