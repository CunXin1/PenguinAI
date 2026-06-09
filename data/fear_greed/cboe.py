"""CBOE volatility index history (free daily CSV — no API key).

  VIX_History.csv:   DATE(MM/DD/YYYY),OPEN,HIGH,LOW,CLOSE   (since 1990)
  VVIX_History.csv:  DATE(MM/DD/YYYY),VVIX                   (close only, since 2006)
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
VVIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VVIX_History.csv"

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PenguinAI/0.1)"}


def _parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _f(v: object) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def _get_csv(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url)
    except Exception:
        logger.warning("CBOE fetch error for %s", url, exc_info=True)
        return None
    if resp.status_code != 200:
        logger.warning("CBOE %s returned HTTP %d", url, resp.status_code)
        return None
    return resp.text


def _parse_vix(text: str) -> list[dict]:
    rows: list[dict] = []
    for r in csv.DictReader(io.StringIO(text)):
        d = _parse_date(r.get("DATE", ""))
        if d is None:
            continue
        close = _f(r.get("CLOSE"))
        if close is None:
            continue
        rows.append(
            {
                "time": d,
                "symbol": "VIX",
                "open": _f(r.get("OPEN")),
                "high": _f(r.get("HIGH")),
                "low": _f(r.get("LOW")),
                "close": close,
            }
        )
    return rows


def _parse_vvix(text: str) -> list[dict]:
    rows: list[dict] = []
    for r in csv.DictReader(io.StringIO(text)):
        d = _parse_date(r.get("DATE", ""))
        if d is None:
            continue
        close = _f(r.get("VVIX"))
        if close is None:
            continue
        rows.append(
            {
                "time": d,
                "symbol": "VVIX",
                "open": None,
                "high": None,
                "low": None,
                "close": close,
            }
        )
    return rows


async def fetch_volatility(
    *, vix_url: str = VIX_URL, vvix_url: str = VVIX_URL, timeout: float = 30.0
) -> list[dict]:
    """Return combined VIX + VVIX daily rows. Empty list on total failure."""
    async with httpx.AsyncClient(
        timeout=timeout, headers=_HEADERS, follow_redirects=True
    ) as client:
        vix_txt = await _get_csv(client, vix_url)
        vvix_txt = await _get_csv(client, vvix_url)

    rows: list[dict] = []
    if vix_txt:
        rows.extend(_parse_vix(vix_txt))
    if vvix_txt:
        rows.extend(_parse_vvix(vvix_txt))
    return rows
