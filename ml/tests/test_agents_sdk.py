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


class TestResearchCardIsolation:
    """Regression: research sub-agents must not mutate the orchestrator's card_sink.

    Previously research_ticker / analyze_watchlist set the SHARED ``ctx.card_sink = None``
    for the sub-agent's duration. If the orchestrator ran another card-emitting tool
    CONCURRENTLY in the same turn, the runner hit ``len(None)`` on the shared sink and
    crashed the stream (and the sibling tool's card was silently dropped). The fix runs
    each sub-agent on an isolated context so the orchestrator's sink is never touched.
    """

    async def test_subagent_runs_on_isolated_context(self, monkeypatch):
        from ml.inference.agents import research as R

        captured: dict = {}

        class _FakeResult:
            final_output = R.TickerVerdict(
                ticker="AAPL", stance="neutral", confidence=0.5, summary="ok"
            )

        async def fake_run(agent, inp, *, context, max_turns):
            captured["ctx"] = context
            # The sub-agent would try to emit cards; its isolated sink is None → no-op.
            if context.card_sink is not None:
                context.card_sink.append({"card": "chart", "data": {"ticker": "AAPL"}})
            return _FakeResult()

        monkeypatch.setattr(R.Runner, "run", fake_run)

        orch_sink: list[dict] = []
        ctx = ChatContext(user_id="u1", db=object(), card_sink=orch_sink)
        out = await R._research("AAPL", ctx)

        assert out["ticker"] == "AAPL"
        # Sub-agent got an ISOLATED context: cards suppressed, identity + db_lock shared.
        assert captured["ctx"] is not ctx
        assert captured["ctx"].card_sink is None
        assert captured["ctx"].user_id == "u1"
        assert captured["ctx"].db_lock is ctx.db_lock
        # The orchestrator's live sink object was never swapped to None nor mutated.
        assert ctx.card_sink is orch_sink
        assert orch_sink == []


@pytest.mark.asyncio
async def test_disabled_chat_returns_error_event(monkeypatch):
    from ml.core.config import ml_settings
    from ml.inference.agents.runner import run_stream

    monkeypatch.setattr(ml_settings, "CHAT_ENABLED", False)
    ctx = ChatContext(user_id="u1", db=object())
    events = [ev async for ev in run_stream("hi", ctx)]
    assert events == [{"type": "error", "detail": "Chat is currently disabled."}]
