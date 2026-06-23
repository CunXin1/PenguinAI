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

from ml.core.config import ml_settings
from ml.inference.llm import LLMBackend, get_llm_backend

logger = logging.getLogger(__name__)


# ── Output schema locked by Agent 2 ──────────────────────────────────────────
AGENT2_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "direction": {"type": "string", "enum": ["LONG", "SHORT", "NEUTRAL"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "holding_period": {
            "type": "string",
            "enum": ["INTRADAY", "SHORT_TERM", "SWING", "POSITION"],
        },
        "ai_attribution": {"type": "string", "maxLength": 300},
        "ai_analysis": {"type": "string", "maxLength": 600},
    },
    "required": ["direction", "confidence", "holding_period", "ai_attribution", "ai_analysis"],
    "additionalProperties": False,
}

AGENT2_SYSTEM_PROMPT = """You are a strict quantitative analyst AI. Synthesize the provided
structured signals across MULTIPLE TIME HORIZONS into one final investment signal JSON.
Use ONLY the data given.

Reading the inputs:
- ensemble_prob_up = short-term (~1 bar) P(price RISES), 0–1. >0.5 bullish, <0.5 bearish.
- ml_horizons holds longer views (may be absent for non-basket tickers):
  - h1w_prob_up = P(price RISES) over ~1 week. >0.5 bullish.
  - h1m_beat_spy / h3m_beat_spy = P(this stock BEATS SPY) over ~1 / ~3 months.
    >0.5 = outperforms the market (bullish lean); <0.5 = lags it (bearish lean).
  For ALL of these, farther from 0.5 = stronger. e.g. 0.38 is BEARISH (~62% the other way),
  NOT "slightly up".
- finbert_mean_score: +bullish/−bearish. fomc_hawk_dove_score: higher = hawkish (LONG headwind).

Direction — SYNTHESIZE all available horizons + sentiment + macro; do NOT key off the
short-term prob alone (it sits near 0.5 for mega-caps and is the WEAKEST signal):
- Lean LONG when the balance of horizons is bullish (most probs > ~0.52); SHORT when
  most are bearish (< ~0.48).
- NEUTRAL ONLY when horizons genuinely CONFLICT (e.g. 1m bullish but 3m bearish with no
  tie-breaker) or all sit ~0.50. Do NOT default to NEUTRAL just because the 1-week prob
  is ~0.5 — the 1m/3m views frequently carry the real signal.

Confidence (must vary, never fixed) = cross-horizon + cross-source AGREEMENT, NOT a single
prob: HIGH (→0.9) when horizons, sentiment and macro all align in one direction; LOW
(→0.5) when they conflict or are all near 0.5. A NEUTRAL call from conflicting horizons is
LOW confidence by definition. Clamp [0.5, 0.95]. Null ML ⇒ NEUTRAL 0.5.

Output: ai_attribution ≤150 chars (1–2 key drivers, name the decisive horizon);
ai_analysis ≤300 chars, data-driven, cite the horizon probs correctly (<0.5 = bearish),
no disclaimers. ONLY the schema JSON."""


@dataclass
class GemmaSignalOutput:
    direction: str
    confidence: float
    holding_period: str
    ai_attribution: str
    ai_analysis: str


class GemmaAgent:
    """Two-step agentic harness over a swappable LLM backend.

    Agent 1 (`assemble_context`) is pure Python — no model call. Agent 2
    (`reason`) calls the configured backend (vLLM / Ollama / hosted API) with a
    locked output schema, then validates + retries with backoff. The backend is
    injectable for tests; in production it's resolved lazily by platform.
    """

    def __init__(self, backend: LLMBackend | None = None):
        self._backend = backend

    @property
    def backend(self) -> LLMBackend:
        if self._backend is None:
            self._backend = get_llm_backend()
        return self._backend

    # ── Agent 1: Factor Assembler ─────────────────────────────────────────────
    def assemble_context(
        self,
        ticker: str,
        xgb_prob_up: float | None,
        rf_prob_up: float | None,
        finbert_score: float | None,
        post_count: int,
        hawk_dove_score: float | None,
        top_posts: list[str],  # RAG-retrieved recent posts (text snippets)
        celebrity_actions: list[dict],  # [{"who": "cathie_wood", "action": "BUY", "date": "..."}]
        earnings_surprise_pct: float | None,
        pe_ratio: float | None,
        ml_horizons: dict[str, dict] | None = None,
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
            "ml_horizons": _summarize_horizons(ml_horizons),
            "sentiment": {
                "finbert_mean_score": finbert_score,
                "post_count_72h": post_count,
                "sample_posts": top_posts[:5],  # max 5 for context length
            },
            "macro_filter": {
                "fomc_hawk_dove_score": hawk_dove_score,
                "interpretation": _interpret_hawk_dove(hawk_dove_score),
            },
            "smart_money": celebrity_actions[:3],  # max 3 recent actions
            "fundamentals": {
                "earnings_surprise_pct": earnings_surprise_pct,
                "pe_ratio": pe_ratio,
            },
        }

    # ── Agent 2: Quant Reasoner ───────────────────────────────────────────────
    async def reason(self, context: dict) -> GemmaSignalOutput:
        """Agent 2: call the LLM backend with a locked JSON output schema."""
        user_message = (
            f"Analyze the following financial signal data for {context['ticker']} "
            f"and output a signal JSON:\n\n{json.dumps(context, indent=2, default=str)}"
        )
        messages = [
            {"role": "system", "content": AGENT2_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        backend = self.backend
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                raw = await backend.chat(
                    messages,
                    schema=AGENT2_OUTPUT_SCHEMA,
                    temperature=ml_settings.GEMMA_TEMPERATURE,
                    max_tokens=ml_settings.GEMMA_MAX_TOKENS,
                )
                return self._validate_output(raw)
            except Exception as e:
                last_exc = e
                wait = 2**attempt
                logger.warning(
                    "Gemma inference attempt %d via %s failed: %s — retrying in %ds",
                    attempt + 1,
                    backend.name,
                    e,
                    wait,
                )
                await asyncio.sleep(wait)

        raise RuntimeError(
            f"Gemma inference failed after 3 attempts (backend={backend.name})"
        ) from last_exc

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


def _summarize_horizons(horizons: dict[str, dict] | None) -> dict:
    """Map basket horizon probs → prompt-friendly keys + a one-line interpretation.

    1w is P(up); 1m/3m are P(beat SPY). Empty/None for tickers in no basket — the
    reasoner then leans on the single short-term ensemble alone.
    """
    if not horizons:
        return {"available": False}
    key = {"1w": "h1w_prob_up", "1m": "h1m_beat_spy", "3m": "h3m_beat_spy"}
    out: dict[str, object] = {"available": True}
    leans: list[str] = []
    for label, h in horizons.items():
        ens = h.get("ensemble")
        if ens is None:
            continue
        out[key.get(label, label)] = ens
        lean = "bullish" if ens > 0.52 else "bearish" if ens < 0.48 else "flat"
        unit = "up" if label == "1w" else "vs SPY"
        leans.append(f"{label} {lean} ({unit})")
    out["interpretation"] = "; ".join(leans) if leans else "no horizon models"
    return out


def _interpret_hawk_dove(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score > 0.3:
        return "hawkish — rate hike pressure, bearish macro"
    if score < -0.3:
        return "dovish — rate cut signal, bullish macro"
    return "neutral macro environment"


gemma_agent = GemmaAgent()
