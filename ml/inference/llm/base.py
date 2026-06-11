"""
LLM backend abstraction — the transport layer beneath the Gemma agents.

A backend knows ONE thing: given OpenAI-style chat messages and (optionally) a
JSON schema, return the model's parsed JSON object. Everything agentic —
context assembly, retries, output validation, fallback — lives one layer up in
`ml.inference.gemma_agent`. This split keeps serving infra (vLLM / Ollama /
hosted API) swappable without touching reasoning logic, and leaves a clean seam
for future finetuned checkpoints and additional backends.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from typing import TypedDict


class ChatMessage(TypedDict):
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str


@dataclass
class ToolCall:
    """A tool invocation requested by the model (one round)."""

    id: str
    name: str
    arguments: dict


@dataclass
class AssistantTurn:
    """Normalized result of a tool-calling completion.

    Either `content` is set (final answer) or `tool_calls` is non-empty (the
    model wants tools run first). The chat agent loops on the latter.
    """

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


def parse_assistant_message(msg: dict) -> AssistantTurn:
    """Parse an OpenAI-format assistant message into an AssistantTurn.

    Shared by the OpenAI-compatible backends (vLLM, hosted API). `arguments`
    arrives as a JSON string per the OpenAI spec; tolerate already-parsed dicts.
    """
    calls: list[ToolCall] = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        raw_args = fn.get("arguments", {})
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except (json.JSONDecodeError, TypeError):
            args = {}
        calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
    return AssistantTurn(content=msg.get("content"), tool_calls=calls)


class LLMBackend(abc.ABC):
    """One inference transport. Implementations: vLLM, Ollama, hosted API."""

    #: Stable identifier for logs / health reporting (e.g. "vllm", "ollama").
    name: str = "base"

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        schema: dict | None = None,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> dict:
        """Run one completion and return the parsed JSON object.

        `schema` is a JSON Schema; when provided the backend MUST constrain the
        model to emit conforming JSON (vLLM guided decoding / Ollama `format` /
        API json_schema). Raises on transport error or unparseable output —
        the agent harness owns retry/backoff.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def health(self) -> bool:
        """True if the backend is reachable and the target model is loadable."""
        raise NotImplementedError

    @abc.abstractmethod
    def model_id(self) -> str:
        """Resolved model identifier this backend will serve."""
        raise NotImplementedError

    async def chat_tools(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AssistantTurn:
        """One tool-calling completion for the chat agent.

        `tools` are OpenAI-format tool schemas. Returns an AssistantTurn that
        either carries a final `content` or a list of `tool_calls` to execute.

        Not every backend supports this — the default raises. Implemented by the
        OpenAI-compatible backends (vLLM `--enable-auto-tool-choice`, hosted API).
        Ollama's Gemma 4 tool-call parser is currently buggy, so it opts out.
        """
        raise NotImplementedError(
            f"{self.name} backend does not support tool calling; use vllm or api"
        )
