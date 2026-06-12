"""Phase 0 spike — prove Gemma 4 tool-calling works through the OpenAI Agents SDK.

Throwaway. Points the SDK at the local Ollama OpenAI-compatible endpoint (/v1),
registers ONE stubbed read-only tool (no DB), and checks:
  1. non-streaming run → the model actually emits a tool call, then a final answer
  2. streaming run → which stream-event types we get (deltas / tool_called / tool_output)

The streaming check validates the event mapping Phase 1 (parity) and Phase 2 (cards)
depend on. Run:  .venv/bin/python scripts/spike_agents_sdk.py
"""

from __future__ import annotations

import asyncio
import os

import httpx
from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    RunContextWrapper,
    Runner,
    function_tool,
    set_tracing_disabled,
)
from openai import AsyncOpenAI
from openai.types.responses import ResponseTextDeltaEvent

OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434") + "/v1"
MODEL_NAME = os.environ.get("SPIKE_MODEL", "gemma4:e4b")

# Local model → no platform.openai.com key; disable tracing export.
set_tracing_disabled(True)
# trust_env=False: never route local serving through a macOS system / HTTP proxy
# (the default httpx client picks one up and returns 502). Mirrors OllamaBackend.
client = AsyncOpenAI(
    base_url=OLLAMA_BASE,
    api_key="ollama",
    http_client=httpx.AsyncClient(trust_env=False, timeout=120.0),
)
model = OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=client)

_tool_calls: list[str] = []


@function_tool
async def get_quote(w: RunContextWrapper, ticker: str) -> dict:
    """Latest price for a US ticker, e.g. AAPL."""
    _tool_calls.append(ticker)
    # Stub — Phase 1 wraps the real _get_quote(ctx.db) handler here instead.
    return {"ticker": ticker.upper(), "price": 211.34, "time": "2026-06-12T15:30:00Z"}


def build_agent() -> Agent:
    return Agent(
        name="spike",
        instructions=(
            "You are PenguinAI's stock assistant. Use the get_quote tool to fetch "
            "prices — never invent numbers. Be concise."
        ),
        model=model,
        tools=[get_quote],
    )


async def test_nonstreaming() -> bool:
    print("\n=== 1. non-streaming run ===")
    _tool_calls.clear()
    result = await Runner.run(build_agent(), "What's the price of AAPL right now?", max_turns=4)
    print("final output:", result.final_output)
    print("tool calls made:", _tool_calls)
    ok = bool(_tool_calls) and "211" in str(result.final_output)
    print("PASS" if ok else "FAIL", "(tool called + price surfaced)")
    return ok


async def test_streaming() -> bool:
    print("\n=== 2. streaming run (event types) ===")
    _tool_calls.clear()
    seen_event_types: set[str] = set()
    seen_item_types: set[str] = set()
    delta_chars = 0

    result = Runner.run_streamed(build_agent(), "Give me AAPL's latest price.", max_turns=4)
    async for ev in result.stream_events():
        seen_event_types.add(ev.type)
        if ev.type == "raw_response_event":
            if isinstance(ev.data, ResponseTextDeltaEvent):
                delta_chars += len(ev.data.delta)
        elif ev.type == "run_item_stream_event":
            seen_item_types.add(ev.item.type)

    print("stream event types :", sorted(seen_event_types))
    print("run-item types     :", sorted(seen_item_types))
    print("delta chars        :", delta_chars)
    print("tool calls made    :", _tool_calls)
    ok = bool(_tool_calls) and delta_chars > 0 and "tool_call_item" in seen_item_types
    print("PASS" if ok else "FAIL", "(tool_call_item seen + text streamed)")
    return ok


async def main() -> None:
    print(f"endpoint={OLLAMA_BASE}  model={MODEL_NAME}")
    a = await test_nonstreaming()
    b = await test_streaming()
    print("\n=== SPIKE", "PASS ===" if (a and b) else "FAIL ===")


if __name__ == "__main__":
    asyncio.run(main())
