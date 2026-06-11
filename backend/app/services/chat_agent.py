"""Backend bridge to the ML chat agent (tool-calling harness).

This is the PREMIUM conversational surface — distinct from ``chat_llm.complete_chat``
(a plain, stateless reply). It runs ``ml.inference.chat.ChatAgent``, which loops the
LLM with read-only tools (quotes, indicators, news, watchlist, …). The agent import
chain is light (httpx + sqlalchemy + pydantic; no torch/transformers).

SECURITY: ``user_id`` is taken from the authenticated request here and passed via
ChatContext — the model never supplies it, so tools can't reach another user's data.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ChatAgentUnavailable(RuntimeError):
    """The model server failed or returned an unusable reply."""


async def run_chat_agent(
    *,
    user_message: str,
    user_id: Any,
    tier: str,
    db: AsyncSession,
    history: list[dict],
    focus_ticker: str | None = None,
) -> tuple[str, list[str]]:
    """Run one user turn to a final answer.

    ``history`` is the prior ``[{role, content}]`` turns of the conversation (the
    new ``user_message`` is added by the agent). Returns ``(reply_text, tools_used)``.
    Raises :class:`ChatAgentUnavailable` on transport failure or empty output so the
    route can refund the quota and return 503.
    """
    # Imported lazily so a stripped/test backend without `ml` still imports this module.
    from ml.inference.chat.agent import chat_agent
    from ml.inference.chat.context import ChatContext

    ctx = ChatContext(
        user_id=str(user_id),
        tier=tier,
        db=db,
        focus_ticker=focus_ticker,
    )
    try:
        result = await chat_agent.chat(user_message, ctx, history=history)
    except Exception as e:  # noqa: BLE001 — transport/parse errors map to 503
        logger.warning("chat agent failed: %s", e)
        raise ChatAgentUnavailable("The assistant is temporarily unavailable.") from e

    content = (result.get("content") or "").strip()
    if not content:
        raise ChatAgentUnavailable("The assistant returned an empty response.")
    return content, result.get("tool_calls_made", [])


async def run_chat_agent_stream(
    *,
    user_message: str,
    user_id: Any,
    tier: str,
    db: AsyncSession,
    history: list[dict],
    focus_ticker: str | None = None,
):
    """Streaming variant of :func:`run_chat_agent`.

    Async-generates the agent's events (``tool`` / ``delta`` / ``done`` / ``error``)
    for the route to relay over SSE. The route owns persistence + quota refund based
    on the terminal ``done``/``error`` event.
    """
    from ml.inference.chat.agent import chat_agent
    from ml.inference.chat.context import ChatContext

    ctx = ChatContext(user_id=str(user_id), tier=tier, db=db, focus_ticker=focus_ticker)
    async for event in chat_agent.chat_stream(user_message, ctx, history=history):
        yield event
