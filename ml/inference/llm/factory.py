"""
Backend selection.

`get_llm_backend()` resolves LLM_BACKEND into a concrete transport. "auto"
picks by platform: Ollama on macOS (Metal), vLLM elsewhere (Windows/Linux GPU).
The result is cached; call `reset_llm_backend()` after changing config in tests.
"""

from __future__ import annotations

import logging
import platform

from ml.core.config import ml_settings
from ml.inference.llm.base import LLMBackend

logger = logging.getLogger(__name__)

_backend: LLMBackend | None = None


def _resolve_backend_name() -> str:
    choice = (ml_settings.LLM_BACKEND or "auto").lower()
    if choice != "auto":
        return choice
    # macOS → Ollama; everything else (Windows/Linux GPU) → vLLM.
    return "ollama" if platform.system() == "Darwin" else "vllm"


def _build(name: str) -> LLMBackend:
    if name == "vllm":
        from ml.inference.llm.vllm_backend import VLLMBackend

        return VLLMBackend()
    if name == "ollama":
        from ml.inference.llm.ollama_backend import OllamaBackend

        return OllamaBackend()
    if name == "api":
        from ml.inference.llm.api_backend import APIBackend

        return APIBackend()
    raise ValueError(f"Unknown LLM_BACKEND: {name!r} (expected auto|vllm|ollama|api)")


def get_llm_backend() -> LLMBackend:
    global _backend
    if _backend is None:
        name = _resolve_backend_name()
        _backend = _build(name)
        logger.info("LLM backend: %s (model=%s)", _backend.name, _backend.model_id())
    return _backend


def reset_llm_backend() -> None:
    """Drop the cached backend (used by tests / after config changes)."""
    global _backend
    _backend = None
