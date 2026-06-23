"""Tests for the OpenAI Agents SDK chat agent (ml.inference.agents).

Covers the parts that do NOT need a live model: the read-only tool gates (server-side
user_id, db availability, error normalization), the compliance guardrail logic, and the
orchestrator wiring (builds with the full tool set + guardrail).
"""

from __future__ import annotations

import pytest

from ml.inference.agents.guardrails import assess_compliance
from ml.inference.agents.tools import _safe
from ml.inference.chat.context import ChatContext


async def _ok(args: dict, ctx: ChatContext) -> dict:
    return {"ok": True, "saw_user": ctx.user_id}


class TestToolGates:
    async def test_requires_user_blocks_guest(self):
        ctx = ChatContext(user_id=None, db=object())
        out = await _safe(_ok, {}, ctx, requires_user=True)
        assert out == {"error": "auth_required", "detail": "log in to use this tool"}

    async def test_requires_db_when_no_connection(self):
        ctx = ChatContext(user_id="u1", db=None)
        out = await _safe(_ok, {}, ctx, requires_db=True)
        assert out["error"] == "unavailable"

    async def test_runs_with_server_side_user(self):
        # The handler reads identity from ctx, never from args — proving args can't spoof a user.
        ctx = ChatContext(user_id="real-user", db=object())
        out = await _safe(_ok, {"user_id": "attacker"}, ctx, requires_user=True)
        assert out == {"ok": True, "saw_user": "real-user"}

    async def test_value_error_becomes_bad_arguments(self):
        async def boom(args, ctx):
            raise ValueError("invalid ticker")

        out = await _safe(boom, {}, ChatContext(user_id="u1", db=object()))
        assert out == {"error": "bad_arguments", "detail": "invalid ticker"}

    async def test_unexpected_error_is_contained(self):
        async def boom(args, ctx):
            raise RuntimeError("db exploded")

        out = await _safe(boom, {}, ChatContext(user_id="u1", db=object()))
        assert out["error"] == "tool_error"


class TestComplianceGuardrail:
    def test_advice_without_disclaimer_is_flagged(self):
        info = assess_compliance("Honestly you should buy NVDA today, it's a sure thing.")
        assert info["advice_language"] and not info["has_disclaimer"]
        assert info["flagged"] is True

    def test_advice_with_disclaimer_is_ok(self):
        info = assess_compliance(
            "You should buy more, but remember this is research, not personalized financial advice."
        )
        assert info["flagged"] is False

    def test_neutral_analysis_is_ok(self):
        info = assess_compliance("NVDA's RSI is 55 and the ML ensemble is 45%, a mixed picture.")
        assert info["advice_language"] is False
        assert info["flagged"] is False


class TestOrchestrator:
    def test_builds_with_full_toolset_and_guardrail(self):
        from ml.inference.agents.agents import build_orchestrator

        agent = build_orchestrator()
        names = {t.name for t in agent.tools}
        assert {"get_quote", "get_signal", "web_fetch_news", "research_ticker", "analyze_watchlist"} <= names
        assert len(agent.output_guardrails) == 1


@pytest.mark.asyncio
async def test_disabled_chat_returns_error_event(monkeypatch):
    from ml.core.config import ml_settings
    from ml.inference.agents.runner import run_stream

    monkeypatch.setattr(ml_settings, "CHAT_ENABLED", False)
    ctx = ChatContext(user_id="u1", db=object())
    events = [ev async for ev in run_stream("hi", ctx)]
    assert events == [{"type": "error", "detail": "Chat is currently disabled."}]
