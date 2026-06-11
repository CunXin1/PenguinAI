"""
Hosted API backend — the plug-in point for future managed inference.

Any OpenAI-compatible endpoint (Google Vertex AI, a gateway, a managed Gemma
host). Selected with LLM_BACKEND="api"; requires GEMMA_API_URL (+ optional
GEMMA_API_KEY). Kept deliberately thin so swapping providers is a config change.
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


class APIBackend(LLMBackend):
    name = "api"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ):
        self._base_url = (base_url or ml_settings.GEMMA_API_URL).rstrip("/")
        self._api_key = api_key if api_key is not None else ml_settings.GEMMA_API_KEY
        self._model = model or ml_settings.GEMMA_API_MODEL
        self._timeout = timeout
        if not self._base_url:
            raise ValueError("LLM_BACKEND='api' requires GEMMA_API_URL to be set")

    def model_id(self) -> str:
        return self._model

    def _endpoint(self) -> str:
        # Allow GEMMA_API_URL to be either the base (".../v1") or the full path.
        if self._base_url.endswith("/chat/completions"):
            return self._base_url
        return f"{self._base_url}/chat/completions"

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
        else:
            payload["response_format"] = {"type": "json_object"}

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._endpoint(), json=payload, headers=headers)
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
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
            "tool_choice": "auto",
        }
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._endpoint(), json=payload, headers=headers)
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
        return parse_assistant_message(msg)

    async def health(self) -> bool:
        return bool(self._base_url)
