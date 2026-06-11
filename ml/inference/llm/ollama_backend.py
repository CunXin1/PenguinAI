"""
Ollama backend — macOS path (Apple Silicon / Metal).

Talks to a local Ollama server (`/api/chat`). Structured output is enforced by
passing the JSON Schema directly as `format`, which constrains decoding to
conforming JSON — the same format-lock guarantee as vLLM guided decoding.

Finetune note: build a derived model from a LoRA/GGUF adapter via a Modelfile
(`FROM gemma4:e2b` + `ADAPTER ./adapter`) — see `ml/serving/Modelfile.gemma` —
then point `OLLAMA_MODEL` at the new tag. No code change required.
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


class OllamaBackend(LLMBackend):
    name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ):
        self._base_url = (base_url or ml_settings.OLLAMA_BASE_URL).rstrip("/")
        self._model = model or ml_settings.ollama_model()
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
            "stream": False,
            # Gemma 4 is a reasoning model: left on, its <thinking> phase consumes
            # the entire num_predict budget before any content is emitted, so a
            # format-constrained call returns done_reason="length" with empty
            # content (→ JSON parse error). Disable thinking so it emits the
            # structured answer directly.
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        # Ollama accepts a JSON Schema object (or the literal "json") as `format`.
        if schema is not None:
            payload["format"] = schema

        # trust_env=False: never route local serving through a system/HTTP proxy.
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
        return json.loads(content)

    async def chat_tools(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AssistantTurn:
        """Tool-calling completion via Ollama's /api/chat `tools` parameter.

        Recent Ollama (>=0.4) parses Gemma 4 tool calls reliably — it returns
        ``message.tool_calls`` (arguments as an object) which parse_assistant_message
        normalizes. ``think`` is disabled so the model emits the final answer (or
        the tool call) directly instead of spending the budget on reasoning.
        """
        payload: dict = {
            "model": self._model,
            "messages": [self._to_ollama_msg(m) for m in messages],
            "stream": False,
            "think": False,
            "tools": tools,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            msg = resp.json().get("message", {})
        return parse_assistant_message(msg)

    @staticmethod
    def _to_ollama_msg(msg: dict) -> dict:
        """Adapt an OpenAI-format history message to Ollama's chat shape.

        The shared chat agent emits OpenAI-standard messages where a replayed
        assistant tool call carries ``function.arguments`` as a JSON *string*.
        Ollama expects an *object* there and silently returns an empty reply
        otherwise, so parse it back. Tool-result messages also get a ``tool_name``
        alias. Plain user/assistant/system turns pass through untouched.
        """
        if msg.get("tool_calls"):
            calls = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                calls.append({"function": {"name": fn.get("name", ""), "arguments": args}})
            return {"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls}
        if msg.get("role") == "tool":
            return {
                "role": "tool",
                "tool_name": msg.get("name") or msg.get("tool_name") or "",
                "content": msg.get("content", ""),
            }
        return msg

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                tags = {m.get("name") for m in resp.json().get("models", [])}
                # Ollama tags are like "gemma4:e2b"; a bare name implies ":latest".
                wanted = self._model if ":" in self._model else f"{self._model}:latest"
                if wanted not in tags:
                    logger.warning(
                        "Ollama reachable but model %s not pulled (have %s). Run: ollama pull %s",
                        wanted,
                        tags,
                        self._model,
                    )
                return True
        except Exception as e:
            logger.warning("Ollama health check failed (%s): %s", self._base_url, e)
            return False
