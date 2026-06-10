"""Tests for the LLM backend layer + Gemma agent harness.

No real server: a FakeBackend is injected so we exercise the harness
(retry/backoff, schema passing, output validation) deterministically.
"""

from __future__ import annotations

import pytest

from ml.inference.gemma_agent import AGENT2_OUTPUT_SCHEMA, GemmaAgent, GemmaSignalOutput
from ml.inference.llm.base import LLMBackend


class FakeBackend(LLMBackend):
    name = "fake"

    def __init__(self, responses, healthy=True):
        # responses: list of dict | Exception, consumed per chat() call
        self._responses = list(responses)
        self._healthy = healthy
        self.calls: list[dict] = []

    async def chat(self, messages, *, schema=None, temperature=0.1, max_tokens=512):
        self.calls.append({"messages": messages, "schema": schema})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def health(self):
        return self._healthy

    def model_id(self):
        return "fake-model"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _instant(_):
        return None

    monkeypatch.setattr("ml.inference.gemma_agent.asyncio.sleep", _instant)


VALID = {
    "direction": "LONG",
    "confidence": 0.82,
    "holding_period": "SWING",
    "ai_attribution": "ML ensemble bullish + positive sentiment",
    "ai_analysis": "Strong ML agreement with supportive sentiment.",
}


def _ctx():
    return GemmaAgent().assemble_context(
        ticker="DEMO",
        xgb_prob_up=0.7,
        rf_prob_up=0.65,
        finbert_score=0.3,
        post_count=10,
        hawk_dove_score=-0.2,
        top_posts=["a", "b"],
        celebrity_actions=[],
        earnings_surprise_pct=5.0,
        pe_ratio=20.0,
    )


class TestHarness:
    @pytest.mark.asyncio
    async def test_happy_path_returns_validated_output(self):
        backend = FakeBackend([VALID])
        agent = GemmaAgent(backend=backend)
        out = await agent.reason(_ctx())
        assert isinstance(out, GemmaSignalOutput)
        assert out.direction == "LONG"
        assert out.confidence == 0.82

    @pytest.mark.asyncio
    async def test_schema_is_passed_to_backend(self):
        backend = FakeBackend([VALID])
        await GemmaAgent(backend=backend).reason(_ctx())
        assert backend.calls[0]["schema"] is AGENT2_OUTPUT_SCHEMA
        roles = [m["role"] for m in backend.calls[0]["messages"]]
        assert roles == ["system", "user"]

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        backend = FakeBackend([RuntimeError("boom"), VALID])
        out = await GemmaAgent(backend=backend).reason(_ctx())
        assert out.direction == "LONG"
        assert len(backend.calls) == 2

    @pytest.mark.asyncio
    async def test_raises_after_three_failures(self):
        backend = FakeBackend([RuntimeError("x"), RuntimeError("y"), RuntimeError("z")])
        with pytest.raises(RuntimeError, match="failed after 3 attempts"):
            await GemmaAgent(backend=backend).reason(_ctx())
        assert len(backend.calls) == 3

    @pytest.mark.asyncio
    async def test_invalid_enum_coerced_to_safe_defaults(self):
        bad = {**VALID, "direction": "MOON", "holding_period": "FOREVER", "confidence": 5}
        out = await GemmaAgent(backend=FakeBackend([bad])).reason(_ctx())
        assert out.direction == "NEUTRAL"
        assert out.holding_period == "SHORT_TERM"
        assert out.confidence == 1.0  # clamped to [0, 1]


class TestFactory:
    def test_auto_selects_by_platform(self, monkeypatch):
        from ml.inference.llm import factory

        monkeypatch.setattr(factory.ml_settings, "LLM_BACKEND", "auto")
        monkeypatch.setattr(factory.platform, "system", lambda: "Darwin")
        assert factory._resolve_backend_name() == "ollama"
        monkeypatch.setattr(factory.platform, "system", lambda: "Windows")
        assert factory._resolve_backend_name() == "vllm"

    def test_explicit_backend_wins(self, monkeypatch):
        from ml.inference.llm import factory

        monkeypatch.setattr(factory.ml_settings, "LLM_BACKEND", "api")
        assert factory._resolve_backend_name() == "api"


class TestModelResolution:
    def test_variant_drives_default_model_ids(self, monkeypatch):
        from ml.core.config import ml_settings

        monkeypatch.setattr(ml_settings, "VLLM_MODEL", "")
        monkeypatch.setattr(ml_settings, "OLLAMA_MODEL", "")
        monkeypatch.setattr(ml_settings, "GEMMA_MODEL_VARIANT", "e2b")
        assert ml_settings.vllm_model() == "google/gemma-4-E2B-it"
        assert ml_settings.ollama_model() == "gemma4:e2b"
        monkeypatch.setattr(ml_settings, "GEMMA_MODEL_VARIANT", "e4b")
        assert ml_settings.vllm_model() == "google/gemma-4-E4B-it"
        assert ml_settings.ollama_model() == "gemma4:e4b"
