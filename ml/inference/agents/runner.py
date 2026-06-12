"""Run one chat turn through the OpenAI Agents SDK and translate to our SSE contract.

The route consumes the SAME event shapes the hand-rolled agent emitted:
  - ``{"type": "tool", "name": ...}``    when a tool is invoked
  - ``{"type": "delta", "text": ...}``   per token of the final answer
  - ``{"type": "done", "content": ..., "tools_used": [...]}``  terminal
  - ``{"type": "error", "detail": ...}`` on a guard/transport failure

Input guards (disabled / empty / too long) mirror the old ``ChatAgent`` exactly:
the streaming path emits ``error`` events; the non-streaming path returns the guard
text as content (so it persists like a normal reply), matching prior behavior.
"""

from __future__ import annotations

import logging

from agents import Runner
from openai.types.responses import ResponseTextDeltaEvent

from ml.core.config import ml_settings
from ml.inference.agents.agents import build_orchestrator
from ml.inference.chat.context import ChatContext

logger = logging.getLogger(__name__)

MAX_TURNS = 6  # parity with the old MAX_TOOL_ROUNDS


def _guard(user_message: str) -> str | None:
    """Return a guard message if the turn should not run, else None."""
    if not ml_settings.CHAT_ENABLED:
        return "Chat is currently disabled."
    if not user_message:
        return "Please enter a message."
    if len(user_message) > ml_settings.CHAT_MAX_INPUT_CHARS:
        return f"Message too long (max {ml_settings.CHAT_MAX_INPUT_CHARS} chars)."
    return None


def _build_input(history: list[dict] | None, user_message: str) -> list[dict]:
    """OpenAI-format input items: trimmed prior turns + the new user message.

    The system prompt lives on the agent (instructions), so history excludes it.
    """
    items: list[dict] = []
    if history:
        items.extend(history[-ml_settings.CHAT_MAX_HISTORY :])
    items.append({"role": "user", "content": user_message})
    return items


def _tool_name(item) -> str:
    """Best-effort function name from a tool_call_item stream item."""
    raw = getattr(item, "raw_item", None)
    for attr in ("name", "function"):
        val = getattr(raw, attr, None)
        if isinstance(val, str):
            return val
        name = getattr(val, "name", None)
        if isinstance(name, str):
            return name
    return "tool"


async def run(user_message: str, ctx: ChatContext, history: list[dict] | None = None) -> dict:
    """Non-streaming turn. Returns ``{content, tool_calls_made}`` (parity with old chat())."""
    user_message = (user_message or "").strip()
    guard = _guard(user_message)
    if guard is not None:
        return {"content": guard, "tool_calls_made": []}

    result = await Runner.run(
        build_orchestrator(), _build_input(history, user_message), context=ctx, max_turns=MAX_TURNS
    )
    tools_used = [
        _tool_name(it) for it in result.new_items if getattr(it, "type", None) == "tool_call_item"
    ]
    return {"content": result.final_output or "", "tool_calls_made": tools_used}


async def run_stream(user_message: str, ctx: ChatContext, history: list[dict] | None = None):
    """Streaming turn — async-generates ``tool`` / ``delta`` / ``done`` / ``error`` events."""
    user_message = (user_message or "").strip()
    guard = _guard(user_message)
    if guard is not None:
        yield {"type": "error", "detail": guard}
        return

    tools_used: list[str] = []
    content_parts: list[str] = []
    final_output = ""
    ctx.card_sink = []  # tools append {"card","data"} here; we drain on each tool output
    emitted_cards = 0
    seen_cards: set[tuple[str, str]] = set()  # dedupe by (card, ticker) — e.g. quote+history → one chart
    try:
        result = Runner.run_streamed(
            build_orchestrator(),
            _build_input(history, user_message),
            context=ctx,
            max_turns=MAX_TURNS,
        )
        async for ev in result.stream_events():
            if ev.type == "raw_response_event":
                data = ev.data
                if isinstance(data, ResponseTextDeltaEvent) and data.delta:
                    content_parts.append(data.delta)
                    yield {"type": "delta", "text": data.delta}
            elif ev.type == "run_item_stream_event":
                if ev.item.type == "tool_call_item":
                    name = _tool_name(ev.item)
                    tools_used.append(name)
                    yield {"type": "tool", "name": name}
                elif ev.item.type == "tool_call_output_item":
                    # The tool has run; flush any cards it recorded, in order.
                    while emitted_cards < len(ctx.card_sink):
                        card = ctx.card_sink[emitted_cards]
                        emitted_cards += 1
                        key = (card["card"], str(card["data"].get("ticker", "")))
                        if key in seen_cards:
                            continue
                        seen_cards.add(key)
                        yield {"type": "card", **card}
        final_output = result.final_output or ""
    except Exception as e:  # noqa: BLE001 — transport/parse errors → error event (route 503s)
        logger.warning("sdk chat stream failed: %s", e)
        yield {"type": "error", "detail": "The assistant is temporarily unavailable."}
        return

    content = "".join(content_parts).strip() or final_output.strip()
    yield {"type": "done", "content": content, "tools_used": tools_used}
