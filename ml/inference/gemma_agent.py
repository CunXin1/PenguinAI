"""
Gemma 4 two-step Agentic reasoning engine.

Agent 1 (Factor Assembler): Collects raw signals → builds structured context JSON.
Agent 2 (Quant Reasoner):   Takes structured context → outputs final signal JSON
                             using Structured Outputs (JSON mode) to lock format.

No free-text user input anywhere in this pipeline. All prompts are backend-assembled.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

import httpx

from ml.core.config import ml_settings

logger = logging.getLogger(__name__)


# ── Output schema locked by Agent 2 ──────────────────────────────────────────
AGENT2_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "direction":      {"type": "string", "enum": ["LONG", "SHORT", "NEUTRAL"]},
        "confidence":     {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "holding_period": {"type": "string", "enum": ["INTRADAY", "SHORT_TERM", "SWING", "POSITION"]},
        "ai_attribution": {"type": "string", "maxLength": 300},
        "ai_analysis":    {"type": "string", "maxLength": 600},
    },
    "required": ["direction", "confidence", "holding_period", "ai_attribution", "ai_analysis"],
    "additionalProperties": False,
}

AGENT2_SYSTEM_PROMPT = """You are a strict quantitative analyst AI. Your ONLY job is to synthesize
the provided structured financial signals into a final investment signal JSON.

Rules:
- Base your reasoning ENTIRELY on the data provided. Do not use outside knowledge.
- confidence must reflect the agreement across all signals (0.5–0.6 = weak, 0.8+ = strong).
- ai_attribution: ≤150 chars. Name the 1–2 strongest factors driving the signal.
- ai_analysis: ≤300 chars. Professional, data-driven. No speculation. No disclaimers.
- Output ONLY valid JSON matching the schema. Nothing else."""


@dataclass
class GemmaSignalOutput:
    direction: str
    confidence: float
    holding_period: str
    ai_attribution: str
    ai_analysis: str


class GemmaAgent:
    def __init__(self):
        self._use_api = bool(ml_settings.GEMMA_API_URL)

    # ── Agent 1: Factor Assembler ─────────────────────────────────────────────
    def assemble_context(
        self,
        ticker: str,
        xgb_prob_up: float | None,
        rf_prob_up: float | None,
        finbert_score: float | None,
        post_count: int,
        hawk_dove_score: float | None,
        top_posts: list[str],          # RAG-retrieved recent posts (text snippets)
        celebrity_actions: list[dict], # [{"who": "cathie_wood", "action": "BUY", "date": "..."}]
        earnings_surprise_pct: float | None,
        pe_ratio: float | None,
    ) -> dict:
        """Agent 1: pure data assembly, no LLM call. Returns structured context."""
        ensemble = None
        if xgb_prob_up is not None and rf_prob_up is not None:
            ensemble = round((xgb_prob_up * 0.6 + rf_prob_up * 0.4), 4)
        elif xgb_prob_up is not None:
            ensemble = xgb_prob_up

        return {
            "ticker": ticker,
            "ml_signals": {
                "xgb_prob_up": xgb_prob_up,
                "rf_prob_up": rf_prob_up,
                "ensemble_prob_up": ensemble,
            },
            "sentiment": {
                "finbert_mean_score": finbert_score,
                "post_count_72h": post_count,
                "sample_posts": top_posts[:5],          # max 5 for context length
            },
            "macro_filter": {
                "fomc_hawk_dove_score": hawk_dove_score,
                "interpretation": _interpret_hawk_dove(hawk_dove_score),
            },
            "smart_money": celebrity_actions[:3],       # max 3 recent actions
            "fundamentals": {
                "earnings_surprise_pct": earnings_surprise_pct,
                "pe_ratio": pe_ratio,
            },
        }

    # ── Agent 2: Quant Reasoner ───────────────────────────────────────────────
    async def reason(self, context: dict) -> GemmaSignalOutput:
        """Agent 2: call Gemma 4 with locked JSON output schema."""
        user_message = (
            f"Analyze the following financial signal data for {context['ticker']} "
            f"and output a signal JSON:\n\n{json.dumps(context, indent=2)}"
        )

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                if self._use_api:
                    raw = await self._call_external_api(user_message)
                else:
                    raw = await self._call_local_inference(user_message)
                return self._validate_output(raw)
            except Exception as e:
                last_exc = e
                wait = 2 ** attempt
                logger.warning("Gemma inference attempt %d failed: %s — retrying in %ds", attempt + 1, e, wait)
                await asyncio.sleep(wait)

        raise RuntimeError(f"Gemma inference failed after 3 attempts") from last_exc

    def _validate_output(self, raw: dict) -> GemmaSignalOutput:
        """Validate Gemma JSON output against expected schema before unpacking."""
        valid_directions = {"LONG", "SHORT", "NEUTRAL"}
        valid_periods = {"INTRADAY", "SHORT_TERM", "SWING", "POSITION"}

        direction = raw.get("direction", "NEUTRAL")
        if direction not in valid_directions:
            direction = "NEUTRAL"

        confidence = float(raw.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        holding_period = raw.get("holding_period", "SHORT_TERM")
        if holding_period not in valid_periods:
            holding_period = "SHORT_TERM"

        return GemmaSignalOutput(
            direction=direction,
            confidence=confidence,
            holding_period=holding_period,
            ai_attribution=str(raw.get("ai_attribution", ""))[:300],
            ai_analysis=str(raw.get("ai_analysis", ""))[:600],
        )

    async def generate_signal(self, **kwargs) -> GemmaSignalOutput:
        """End-to-end: assemble context then reason."""
        context = self.assemble_context(**kwargs)
        return await self.reason(context)

    # ── Inference backends ────────────────────────────────────────────────────
    async def _call_local_inference(self, user_message: str) -> dict:
        """Call local vLLM server (default: http://localhost:8080)."""
        url = ml_settings.GEMMA_API_URL or "http://localhost:8080/v1/chat/completions"
        payload = {
            "model": ml_settings.GEMMA_MODEL_PATH,
            "messages": [
                {"role": "system", "content": AGENT2_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": ml_settings.GEMMA_TEMPERATURE,
            "max_tokens": ml_settings.GEMMA_MAX_TOKENS,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "signal_output", "schema": AGENT2_OUTPUT_SCHEMA},
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)

    async def _call_external_api(self, user_message: str) -> dict:
        """Call external Gemma API (e.g. Google Vertex AI). Same OpenAI-compatible format."""
        payload = {
            "model": "gemma-4",
            "messages": [
                {"role": "system", "content": AGENT2_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": ml_settings.GEMMA_TEMPERATURE,
            "max_tokens": ml_settings.GEMMA_MAX_TOKENS,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {ml_settings.GEMMA_API_KEY}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(ml_settings.GEMMA_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)


def _interpret_hawk_dove(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score > 0.3:
        return "hawkish — rate hike pressure, bearish macro"
    if score < -0.3:
        return "dovish — rate cut signal, bullish macro"
    return "neutral macro environment"


gemma_agent = GemmaAgent()
