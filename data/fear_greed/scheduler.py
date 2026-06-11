"""Background scheduler for Fear & Greed + VIX/VVIX.

CNN updates the live index several times during the regular session, so the
cadence is session-aware (NYSE calendar, injected as ``phase_fn``):

    REGULAR      → every 8 min   (env FEAR_GREED_RTH_MIN, default 8)
    PRE_MARKET   → every 15 min  (catch the reading right before the open)
    AFTER_HOURS  → every 15 min  (catch the finalized reading after the close)
    OVERNIGHT    → every 60 min  (heartbeat; the value is static off-session)
    CLOSED       → every 60 min  (weekends / holidays; also detects recovery)

On top of the cadence:
  * **startup** — one fetch as soon as the thread starts (covers a restart).
  * **session boundaries** — a forced fetch the moment the phase changes, so the
    open and the close each get a fresh pull exactly on time.
  * **staleness guard** — if the last *successful* fetch is older than
    FEAR_GREED_STALE_MIN (default 90 min), force a fetch without waiting for the
    cadence (e.g. recovering from an outage).

Health (last success, source, failures, score, next run) is published into the
shared ``health`` dict so the admin panel can show when the CNN endpoint breaks.
``source == "computed"`` means CNN was unreachable and the VIX-proxy fallback ran.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from time import monotonic

from .loader import latest_fng_time, run_loader

logger = logging.getLogger(__name__)

# Cadence per session phase, in minutes. REGULAR is overridable via env.
_PHASE_INTERVAL_MIN = {
    "REGULAR": int(os.getenv("FEAR_GREED_RTH_MIN", "8")),
    "PRE_MARKET": 15,
    "AFTER_HOURS": 15,
    "OVERNIGHT": 60,
    "CLOSED": 60,
}
# Re-evaluate the session phase at least this often so open/close boundaries and
# the staleness guard are noticed promptly even inside a long overnight wait.
_TICK_S = 60.0


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _interval_min(phase: str) -> int:
    return _PHASE_INTERVAL_MIN.get(phase, 60)


async def _cycle(db_url: str) -> dict:
    """Run one loader pass and read back the newest stored row time."""
    result = await run_loader(db_url)
    result["latest_row_time"] = await latest_fng_time(db_url)
    return result


def run_scheduler(
    stop_event: threading.Event,
    db_url: str,
    *,
    health: dict | None = None,
    phase_fn=None,
) -> None:
    """Entry point for the background thread. Blocks until ``stop_event`` is set.

    ``phase_fn(now_utc) -> str`` returns the NYSE session phase; injected by the
    backend (``app.core.market_clock.get_session_phase``) to keep this module free
    of any backend import. Without it, every tick is treated as REGULAR (safe: a
    constant 8-min cadence).
    """
    phase_fn = phase_fn or (lambda _now: "REGULAR")
    stale_after_s = max(60, int(os.getenv("FEAR_GREED_STALE_MIN", "90")) * 60)
    health = health if health is not None else {}
    health.setdefault("consecutive_failures", 0)

    def _publish(**fields) -> None:
        health.update(fields)

    def _pull(reason: str) -> None:
        now = datetime.now(UTC)
        _publish(last_run_at=_iso(now), last_reason=reason)
        try:
            res = asyncio.run(_cycle(db_url))
        except Exception as exc:  # noqa: BLE001 — never let the thread die
            health["consecutive_failures"] = health.get("consecutive_failures", 0) + 1
            _publish(last_error=f"{type(exc).__name__}: {exc}")
            logger.warning("fear&greed scheduler: %s fetch failed", reason, exc_info=True)
            return

        if res.get("ok"):
            health["consecutive_failures"] = 0
            _publish(
                last_success_at=_iso(datetime.now(UTC)),
                last_error=None if res.get("source") == "cnn" else "CNN unavailable (VIX proxy)",
                source=res.get("source"),
                score=res.get("score"),
                rating=res.get("rating"),
                latest_row_time=_iso(res.get("latest_row_time")),
            )
            logger.info(
                "fear&greed scheduler: %s — %d rows (score=%s source=%s)",
                reason, res.get("rows"), res.get("score"), res.get("source"),
            )
        else:
            health["consecutive_failures"] = health.get("consecutive_failures", 0) + 1
            _publish(last_error="no data from CNN or VIX fallback")
            logger.warning("fear&greed scheduler: %s produced no Fear&Greed reading", reason)

    # Pull immediately on startup, then run the cadence loop.
    last_phase: str | None = None
    next_due = monotonic()  # due now

    while not stop_event.is_set():
        now_m = monotonic()
        now = datetime.now(UTC)
        phase = phase_fn(now)
        interval_min = _interval_min(phase)

        boundary = last_phase is not None and phase != last_phase
        due = now_m >= next_due
        last_ok = health.get("last_success_at")
        stale = False
        if last_ok:
            try:
                age = (now - datetime.fromisoformat(last_ok)).total_seconds()
                stale = age > stale_after_s
            except ValueError:
                stale = False

        if due or boundary or stale:
            reason = (
                f"boundary→{phase}" if boundary
                else "startup" if last_phase is None
                else "stale-catchup" if stale and not due
                else phase
            )
            _pull(reason)
            next_due = monotonic() + interval_min * 60

        last_phase = phase
        remaining = max(0.0, next_due - monotonic())
        _publish(
            phase=phase,
            interval_min=interval_min,
            next_run_at=_iso(datetime.now(UTC) + timedelta(seconds=remaining)),
        )

        sleep_s = min(_TICK_S, max(1.0, next_due - monotonic()))
        if stop_event.wait(timeout=sleep_s):
            break
