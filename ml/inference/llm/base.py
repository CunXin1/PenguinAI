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
from typing import TypedDict


class ChatMessage(TypedDict):
    role: str  # "system" | "user" | "assistant"
    content: str


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
