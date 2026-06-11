"""
vLLM backend — Windows / Linux GPU path.

Talks to a local vLLM server exposing the OpenAI-compatible API
(`/v1/chat/completions`). Structured output is enforced via guided decoding
(`response_format: json_schema`), so Agent 2's output JSON is format-locked.

Finetune note: point `VLLM_MODEL` at a merged checkpoint dir, or launch the
server with `--enable-lora --lora-modules <name>=<path>` and set `VLLM_MODEL`
to that LoRA name. Nothing here changes — the model id is config-driven.
"""

from __future__ import annotations

import json
import logging

import httpx

from ml.core.config import ml_settings
from ml.inference.llm.base import (
    AssistantTurn,
    ChatMessage,
    LLMBackend,
    parse_assistant_message,
)

logger = logging.getLogger(__name__)


class VLLMBackend(LLMBackend):
    name = "vllm"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ):
        self._base_url = (base_url or ml_settings.VLLM_BASE_URL).rstrip("/")
        self._model = model or ml_settings.vllm_model()
        self._timeout = timeout

    def model_id(self) -> str:
        return self._model

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        schema: dict | None = None,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> dict:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "signal_output", "schema": schema},
            }

        # trust_env=False: never route local serving through a system/HTTP proxy.
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            resp = await client.post(f"{self._base_url}/chat/completions", json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    async def chat_tools(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AssistantTurn:
        """Tool-calling via vLLM. Requires the server started with
        `--enable-auto-tool-choice` and a tool parser for Gemma 4."""
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
            "tool_choice": "auto",
        }
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            resp = await client.post(f"{self._base_url}/chat/completions", json=payload)
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
        return parse_assistant_message(msg)

    async def chat_tools_stream(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ):
        """Streaming variant of :meth:`chat_tools` over the OpenAI SSE protocol.

        Async-generates ``{"type": "delta", "text": ...}`` per content token, then a
        ``{"type": "final", "turn": AssistantTurn}``. OpenAI-style tool calls stream
        as fragments keyed by ``index`` (name once, arguments concatenated across
        chunks), so they are reassembled before the final parse. Mirrors the Ollama
        backend so the chat agent streams identically on either transport.
        """
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
        }
        content_parts: list[str] = []
        tool_acc: dict[int, dict] = {}
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            async with client.stream(
                "POST", f"{self._base_url}/chat/completions", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        choices = json.loads(data).get("choices") or []
                    except json.JSONDecodeError:
                        continue
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                        yield {"type": "delta", "text": delta["content"]}
                    for tc in delta.get("tool_calls") or []:
                        slot = tool_acc.setdefault(
                            tc.get("index", 0), {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
        tool_calls = [
            {"id": s["id"], "function": {"name": s["name"], "arguments": s["arguments"]}}
            for _, s in sorted(tool_acc.items())
        ]
        yield {
            "type": "final",
            "turn": parse_assistant_message(
                {"content": "".join(content_parts), "tool_calls": tool_calls}
            ),
        }

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                resp = await client.get(f"{self._base_url}/models")
                resp.raise_for_status()
                ids = {m.get("id") for m in resp.json().get("data", [])}
                if self._model not in ids:
                    logger.warning(
                        "vLLM reachable but model %s not in served set %s", self._model, ids
                    )
                return True
        except Exception as e:
            logger.warning("vLLM health check failed (%s): %s", self._base_url, e)
            return False
