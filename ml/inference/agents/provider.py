"""Model provider for the SDK-based chat agent.

Resolves ``LLM_BACKEND`` into an OpenAI-compatible client pointed at our local
vLLM/Ollama server (or an external API), and exposes per-role model tiers
(``main_model`` for the user-facing orchestrator, ``narrow_model`` for single-ticker
sub-agents). The transport is identical to the signal pipeline's backends — same
endpoints, same resolved Gemma 4 tags — just driven through the Agents SDK instead.

IMPORTANT: local serving MUST use a ``trust_env=False`` httpx client. The default
client picks up a macOS System Configuration proxy and 502s on localhost — the same
guard the hand-rolled ``OllamaBackend`` already applies.
"""

from __future__ import annotations

import logging
import platform
from functools import lru_cache

import httpx
from agents import ModelSettings, OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI

from ml.core.config import ml_settings

logger = logging.getLogger(__name__)


def _resolve() -> tuple[str, str, str]:
    """Return ``(base_url, api_key, model)`` for the configured backend.

    Mirrors ``ml.inference.llm.factory``: "auto" → Ollama on macOS, vLLM elsewhere.
    Ollama's OpenAI-compatible surface lives under ``/v1``; vLLM's base URL already
    includes it.
    """
    choice = (ml_settings.LLM_BACKEND or "auto").lower()
    if choice == "auto":
        choice = "ollama" if platform.system() == "Darwin" else "vllm"

    if choice == "ollama":
        return (
            ml_settings.OLLAMA_BASE_URL.rstrip("/") + "/v1",
            "ollama",  # Ollama ignores the key but the SDK requires a non-empty one
            ml_settings.ollama_model(),
        )
    if choice == "vllm":
        return ml_settings.VLLM_BASE_URL.rstrip("/"), "EMPTY", ml_settings.vllm_model()
    if choice == "api":
        if not ml_settings.GEMMA_API_URL:
            raise ValueError("LLM_BACKEND='api' requires GEMMA_API_URL to be set")
        return (
            ml_settings.GEMMA_API_URL.rstrip("/"),
            ml_settings.GEMMA_API_KEY or "EMPTY",
            ml_settings.GEMMA_API_MODEL,
        )
    raise ValueError(f"Unknown LLM_BACKEND: {choice!r} (expected auto|vllm|ollama|api)")


@lru_cache(maxsize=1)
def _client_and_default_model() -> tuple[AsyncOpenAI, str]:
    base_url, api_key, model = _resolve()
    set_tracing_disabled(True)  # no platform.openai.com key in this deployment
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        http_client=httpx.AsyncClient(trust_env=False, timeout=float(ml_settings.CHAT_TIMEOUT_SECONDS)),
    )
    logger.info("chat agent (SDK) LLM: base_url=%s model=%s", base_url, model)
    return client, model


def _model(name_override: str) -> OpenAIChatCompletionsModel:
    client, default_model = _client_and_default_model()
    return OpenAIChatCompletionsModel(model=name_override or default_model, openai_client=client)


def chat_model_settings() -> ModelSettings:
    """Generation settings shared by every SDK agent.

    Applies the CHAT_* caps the hand-rolled path already honored (the SDK path
    previously used library defaults), and passes ``num_ctx`` to the local server via
    ``extra_body`` so the request isn't capped at Ollama's 4096 default. NOTE: whether
    the OpenAI-compatible /v1 endpoint honors ``options.num_ctx`` depends on the server;
    the guaranteed knob is the ``OLLAMA_CONTEXT_LENGTH`` env var on ``ollama serve``.
    """
    return ModelSettings(
        temperature=ml_settings.CHAT_TEMPERATURE,
        max_tokens=ml_settings.CHAT_MAX_TOKENS,
        extra_body={"options": {"num_ctx": ml_settings.CHAT_NUM_CTX}},
    )


def main_model() -> OpenAIChatCompletionsModel:
    """User-facing orchestrator / synthesis tier (configurable to a bigger model/API)."""
    return _model(ml_settings.CHAT_MAIN_MODEL)


def narrow_model() -> OpenAIChatCompletionsModel:
    """Narrow single-ticker sub-agent tier — a local small model (E4B) is sufficient."""
    return _model(ml_settings.CHAT_NARROW_MODEL)


def reset_provider() -> None:
    """Drop the cached client (tests / after config changes)."""
    _client_and_default_model.cache_clear()
