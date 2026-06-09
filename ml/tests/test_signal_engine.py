"""Unit tests for SignalEngine — focuses on logic that doesn't need DB or models."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ml.inference.gemma_agent import GemmaSignalOutput
from ml.inference.signal_engine import SignalEngine


@pytest.fixture
def engine():
    return SignalEngine()


@pytest.fixture
def mock_db():
    mock = AsyncMock()

    mappings_obj = MagicMock()
    mappings_obj.first.return_value = None
    mappings_obj.all.return_value = []

    result = MagicMock()
    result.mappings.return_value = mappings_obj
    result.scalar_one_or_none.return_value = None
    result.all.return_value = []

    mock.execute.return_value = result
    return mock


class TestComputeNeutralFallback:
    @pytest.mark.asyncio
    async def test_no_indicators_returns_neutral(self, engine, mock_db):
        result = await engine.compute("FAKE", mock_db)
        assert result["direction"] == "NEUTRAL"
        assert result["confidence"] == 0.5
        assert result["ai_attribution"] == "insufficient_data"
        assert result["ticker"] == "FAKE"

    @pytest.mark.asyncio
    async def test_neutral_has_all_required_keys(self, engine, mock_db):
        result = await engine.compute("TEST", mock_db)
        required = {
            "ticker", "direction", "confidence", "holding_period",
            "xgb_prob_up", "rf_prob_up", "ensemble_prob",
            "finbert_score", "post_count", "hawk_dove_ref",
            "ai_attribution", "ai_analysis",
            "tier_required", "computed_at", "expires_at",
        }
        assert required.issubset(result.keys())


class TestMacroFilter:
    def test_hawkish_dampens_long(self, engine):
        direction, conf = engine._apply_macro_filter("LONG", 0.8, 0.7)
        assert conf == round(0.8 * 0.85, 4)
        assert direction == "LONG"

    def test_hawkish_flips_weak_long_to_neutral(self, engine):
        direction, conf = engine._apply_macro_filter("LONG", 0.6, 0.7)
        assert direction == "NEUTRAL"

    def test_short_unaffected(self, engine):
        direction, conf = engine._apply_macro_filter("SHORT", 0.8, 0.9)
        assert direction == "SHORT"
        assert conf == 0.8

    def test_none_hawk_dove_noop(self, engine):
        direction, conf = engine._apply_macro_filter("LONG", 0.8, None)
        assert direction == "LONG"
        assert conf == 0.8

    def test_dovish_noop(self, engine):
        direction, conf = engine._apply_macro_filter("LONG", 0.8, 0.3)
        assert direction == "LONG"
        assert conf == 0.8


class TestFallbackGemma:
    def test_both_probs_available(self, engine):
        out = engine._fallback_gemma_output(0.7, 0.6, 0.5)
        assert out.direction == "LONG"
        assert out.confidence > 0.5
        assert isinstance(out, GemmaSignalOutput)

    def test_bearish_probs(self, engine):
        out = engine._fallback_gemma_output(0.3, 0.2, -0.5)
        assert out.direction == "SHORT"

    def test_neutral_probs(self, engine):
        out = engine._fallback_gemma_output(0.5, 0.5, 0.0)
        assert out.direction == "NEUTRAL"

    def test_all_none(self, engine):
        out = engine._fallback_gemma_output(None, None, None)
        assert out.direction == "NEUTRAL"
        assert out.confidence == 0.5
        assert "insufficient" in out.ai_attribution

    def test_only_xgb(self, engine):
        out = engine._fallback_gemma_output(0.8, None, None)
        assert out.direction == "LONG"
