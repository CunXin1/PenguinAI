"""Tests for the chat agent harness + tool registry.

A FakeToolBackend scripts AssistantTurn responses so the tool-calling loop runs
deterministically with no model. A FakeDB records SQL params so we can prove the
server-side user_id (not model args) is what reaches user-scoped queries.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ml.inference.chat import ChatAgent, ChatContext, build_default_registry
from ml.inference.chat.tools import _ticker
from ml.inference.llm.base import AssistantTurn, LLMBackend, ToolCall


class FakeToolBackend(LLMBackend):
    name = "faketool"

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = []

    async def chat(self, *a, **k):
        raise NotImplementedError

    async def chat_tools(self, messages, *, tools, temperature=0.7, max_tokens=1024):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self._turns.pop(0)

    async def health(self):
        return True

    def model_id(self):
        return "fake"


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        m = MagicMock()
        m.all.return_value = self._rows
        m.first.return_value = self._rows[0] if self._rows else None
        return m


class FakeDB:
    def __init__(self, rows=None):
        self.calls = []
        self._rows = rows or []

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))
        return FakeResult(self._rows)


# ── harness loop ─────────────────────────────────────────────────────────────
class TestChatLoop:
    @pytest.mark.asyncio
    async def test_tool_then_final_answer(self):
        backend = FakeToolBackend(
            [
                AssistantTurn(tool_calls=[ToolCall("c1", "web_search", {"query": "NVDA"})]),
                AssistantTurn(content="Here is what I found."),
            ]
        )
        agent = ChatAgent(backend=backend)
        ctx = ChatContext(user_id="u-1", tier="PREMIUM", db=None)

        out = await agent.chat("what's new with NVDA?", ctx)

        assert out["content"] == "Here is what I found."
        assert out["tool_calls_made"] == ["web_search"]
        assert out["rounds"] == 1
        # second model call must include the tool result fed back as a tool message
        second_call_msgs = backend.calls[1]["messages"]
        assert any(m.get("role") == "tool" and m.get("name") == "web_search" for m in second_call_msgs)

    @pytest.mark.asyncio
    async def test_direct_answer_no_tools(self):
        backend = FakeToolBackend([AssistantTurn(content="Hello!")])
        out = await ChatAgent(backend=backend).chat("hi", ChatContext(user_id="u-1"))
        assert out["content"] == "Hello!"
        assert out["tool_calls_made"] == []
        assert len(backend.calls) == 1

    @pytest.mark.asyncio
    async def test_input_too_long_short_circuits(self, monkeypatch):
        backend = FakeToolBackend([])
        out = await ChatAgent(backend=backend).chat("x" * 5000, ChatContext(user_id="u-1"))
        assert out["error"] == "input_too_long"
        assert backend.calls == []  # never reached the model

    @pytest.mark.asyncio
    async def test_disabled(self, monkeypatch):
        from ml.core.config import ml_settings

        monkeypatch.setattr(ml_settings, "CHAT_ENABLED", False)
        out = await ChatAgent(backend=FakeToolBackend([])).chat("hi", ChatContext(user_id="u-1"))
        assert out["error"] == "disabled"


# ── security / tenancy ───────────────────────────────────────────────────────
class TestToolSecurity:
    @pytest.mark.asyncio
    async def test_watchlist_uses_ctx_user_not_args(self):
        """A forged user_id in tool args must be ignored — only ctx.user_id reaches SQL."""
        reg = build_default_registry()
        db = FakeDB(rows=[{"ticker": "AAPL", "added_at": "2026-01-01T00:00:00Z"}])
        ctx = ChatContext(user_id="real-user", db=db)

        result = await reg.dispatch("get_watchlist", {"user_id": "ATTACKER"}, ctx)

        assert "watchlist" in result
        _, params = db.calls[0]
        assert params == {"u": "real-user"}  # server-side identity won

    @pytest.mark.asyncio
    async def test_user_tool_requires_login(self):
        reg = build_default_registry()
        ctx = ChatContext(user_id=None, db=FakeDB())  # guest
        result = await reg.dispatch("get_watchlist", {}, ctx)
        assert result["error"] == "auth_required"

    @pytest.mark.asyncio
    async def test_db_tool_unavailable_without_db(self):
        reg = build_default_registry()
        ctx = ChatContext(user_id="u-1", db=None)
        result = await reg.dispatch("get_quote", {"ticker": "AAPL"}, ctx)
        assert result["error"] == "unavailable"

    def test_ticker_validation(self):
        assert _ticker({"ticker": "aapl"}) == "AAPL"
        for bad in ["", "TOOLONGTICKER", "A B", "'; DROP TABLE", "../x"]:
            with pytest.raises(ValueError):
                _ticker({"ticker": bad})


# ── registry / stubs ─────────────────────────────────────────────────────────
class TestRegistry:
    def test_schemas_are_openai_shaped(self):
        reg = build_default_registry()
        schemas = reg.openai_schemas()
        names = {s["function"]["name"] for s in schemas}
        assert {"get_quote", "get_watchlist", "get_news", "web_search"} <= names
        for s in schemas:
            assert s["type"] == "function"
            assert "parameters" in s["function"]

    def test_user_tools_dont_expose_user_field(self):
        reg = build_default_registry()
        for s in reg.openai_schemas():
            props = s["function"]["parameters"].get("properties", {})
            assert "user_id" not in props and "user" not in props

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        reg = build_default_registry()
        assert (await reg.dispatch("nope", {}, ChatContext(user_id="u")))["error"] == "unknown_tool"

    @pytest.mark.asyncio
    async def test_stub_tools(self):
        reg = build_default_registry()
        ctx = ChatContext(user_id="u-1", db=FakeDB())
        assert (await reg.dispatch("get_portfolio", {}, ctx))["error"] == "not_available"
        assert (await reg.dispatch("web_search", {"query": "x"}, ctx))["error"] == "not_configured"


# ── backend capability ───────────────────────────────────────────────────────
class TestBackendToolSupport:
    @pytest.mark.asyncio
    async def test_ollama_supports_tool_calling(self):
        # Ollama's Gemma 4 tool-call parser works (>=0.4): OllamaBackend overrides
        # chat_tools with a real implementation rather than the base opt-out, so the
        # chat agent runs the full tool loop on macOS. (The old "must use vLLM" caveat
        # is obsolete.)
        from ml.inference.llm.base import LLMBackend
        from ml.inference.llm.ollama_backend import OllamaBackend

        assert OllamaBackend.chat_tools is not LLMBackend.chat_tools
