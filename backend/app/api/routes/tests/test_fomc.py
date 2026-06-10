"""Tests for FOMC endpoints + the shared meeting calendar (data/fomc/meetings.py).

The SQLite test DB has no fomc_* / bars_1d tables, so the DB-backed endpoints
exercise the graceful-degradation guards added during cleanup: they must return
a clean empty/default payload (HTTP 200), never a 500.
"""

import pytest
from httpx import AsyncClient

from data.fomc.meetings import FOMC_MEETINGS, meetings_need_update, next_meeting_date

# ── data/fomc/meetings.py — pure, deterministic units ─────────────────────────


def test_next_meeting_date_picks_first_on_or_after_today():
    assert next_meeting_date("2026-06-10") == "2026-06-17"


def test_next_meeting_date_is_inclusive_of_today():
    assert next_meeting_date("2025-01-29") == "2025-01-29"


def test_next_meeting_date_exhausted_returns_none():
    assert next_meeting_date("2099-01-01") is None


def test_fomc_meetings_sorted_and_nonempty():
    assert sorted(FOMC_MEETINGS) == FOMC_MEETINGS
    assert len(FOMC_MEETINGS) > 0


def test_meetings_need_update_with_huge_threshold_is_true():
    # A ~273-year horizon means the tail is always "near" → True regardless of date.
    assert meetings_need_update(within_days=100_000) is True


# ── Pure endpoints (no DB) ────────────────────────────────────────────────────


async def test_next_meeting_endpoint(client: AsyncClient):
    resp = await client.get("/api/fomc/next-meeting")
    assert resp.status_code == 200
    body = resp.json()
    assert "next_meeting" in body
    assert "days_until" in body


async def test_schedule_endpoint(client: AsyncClient):
    resp = await client.get("/api/fomc/schedule")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── DB-backed endpoints → must degrade gracefully (table absent on SQLite) ─────


@pytest.mark.parametrize(
    "path",
    ["/api/fomc/statements", "/api/fomc/trend", "/api/fomc/market-reaction",
     "/api/fomc/rate-probabilities"],
)
async def test_db_endpoints_degrade_to_empty_list(client: AsyncClient, path: str):
    resp = await client.get(path)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_diff_degrades_to_error_payload(client: AsyncClient):
    # Valid date, but the statements table is absent → guard returns a 200 error body.
    resp = await client.get("/api/fomc/diff?date=2025-01-29")
    assert resp.status_code == 200
    assert "error" in resp.json()
