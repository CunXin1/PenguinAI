"""
Ollama backend — macOS path (Apple Silicon / Metal).

Talks to a local Ollama server (`/api/chat`). Structured output is enforced by
passing the JSON Schema directly as `format`, which constrains decoding to
conforming JSON — the same format-lock guarantee as vLLM guided decoding.

Finetune note: build a derived model from a LoRA/GGUF adapter via a Modelfile
(`FROM gemma3n:e2b` + `ADAPTER ./adapter`) — see `ml/serving/Modelfile.gemma` —
then point `OLLAMA_MODEL` at the new tag. No code change required.
"""

from __future__ import annotations

import json
import logging

import httpx

from ml.core.config import ml_settings
from ml.inference.llm.base import ChatMessage, LLMBackend

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
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        # Ollama accepts a JSON Schema object (or the literal "json") as `format`.
        if schema is not None:
            payload["format"] = schema

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
        return json.loads(content)

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                tags = {m.get("name") for m in resp.json().get("models", [])}
                # Ollama tags are like "gemma3n:e2b"; bare "gemma3n" implies ":latest".
                wanted = self._model if ":" in self._model else f"{self._model}:latest"
                if wanted not in tags:
                    logger.warning(
                        "Ollama reachable but model %s not pulled (have %s). "
                        "Run: ollama pull %s",
                        wanted,
                        tags,
                        self._model,
                    )
                return True
        except Exception as e:
            logger.warning("Ollama health check failed (%s): %s", self._base_url, e)
            return False
