"""
Main signal generation orchestrator.
Coordinates: feature engineering → ML models → RAG retrieval → Gemma 4 → signal output.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from ml.core.config import ml_settings
from ml.features.fundamental import get_fundamentals
from ml.features.sentiment import get_ticker_sentiment
from ml.features.technical import features_to_dict
from ml.inference.gemma_agent import GemmaSignalOutput, gemma_agent
from ml.models.model_registry import model_registry
from ml.models.xgboost_trainer import FEATURE_COLS
from ml.rag.retriever import rag_retriever

logger = logging.getLogger(__name__)


class SignalEngine:
    """
    Orchestrates full signal computation for a single ticker.
    Called by Celery tasks (both hourly Top-100 and on-demand cold tickers).
    """

    async def compute(self, ticker: str, db_session) -> dict:
        """
        Full pipeline: fetch data → features → ML → RAG → Gemma → signal dict.

        Returns a dict matching the signal_cache table schema.
        """
        logger.info("Computing signal for %s", ticker)

        # ── 1. Load the latest precomputed feature row (indicators_30min view) ─
        feature_row = await self._load_features(ticker, db_session)
        if feature_row is None:
            logger.warning("No indicator data for %s", ticker)
            return self._neutral_signal(ticker, reason="insufficient_data")

        # ── 2. Technical features (already model-ready; no recomputation) ──────
        feature_dict = features_to_dict(feature_row)

        # ── 3. ML model inference ─────────────────────────────────────────────
        xgb_prob_up = model_registry.predict_xgb(ticker, feature_dict)
        rf_prob_up = model_registry.predict_rf(ticker, feature_dict)

        # ── 4. Sentiment (FinBERT aggregated from social_posts) ───────────────
        finbert_score, post_count = await get_ticker_sentiment(ticker, db_session, hours=72)

        # ── 5. RAG: retrieve top relevant posts ──────────────────────────────
        top_posts = await rag_retriever.retrieve(ticker=ticker, top_k=5, db=db_session)

        # ── 6. Fundamentals + smart money ────────────────────────────────────
        earnings_surprise, pe_ratio = await get_fundamentals(ticker, db_session)
        celebrity_actions = await self._get_celebrity_actions(ticker, db_session)

        # ── 7. FOMC macro filter ──────────────────────────────────────────────
        hawk_dove_score = await self._get_latest_fomc(db_session)

        # ── 8. Gemma 4 two-step agentic reasoning ────────────────────────────
        try:
            gemma_output: GemmaSignalOutput = await gemma_agent.generate_signal(
                ticker=ticker,
                xgb_prob_up=xgb_prob_up,
                rf_prob_up=rf_prob_up,
                finbert_score=finbert_score,
                post_count=post_count,
                hawk_dove_score=hawk_dove_score,
                top_posts=top_posts,
                celebrity_actions=celebrity_actions,
                earnings_surprise_pct=earnings_surprise,
                pe_ratio=pe_ratio,
            )
        except Exception as e:
            logger.warning("Gemma unavailable for %s: %s — using ML-only signal", ticker, e)
            gemma_output = self._fallback_gemma_output(xgb_prob_up, rf_prob_up, finbert_score)

        # ── 9. Apply global FOMC override ────────────────────────────────────
        direction, confidence = self._apply_macro_filter(
            gemma_output.direction,
            gemma_output.confidence,
            hawk_dove_score,
        )

        now = datetime.now(UTC)
        return {
            "ticker": ticker,
            "direction": direction,
            "confidence": round(confidence, 4),
            "holding_period": gemma_output.holding_period,
            "xgb_prob_up": xgb_prob_up,
            "rf_prob_up": rf_prob_up,
            "ensemble_prob": (
                round(((xgb_prob_up or 0) * 0.6 + (rf_prob_up or 0) * 0.4), 4)
                if xgb_prob_up is not None or rf_prob_up is not None
                else None
            ),
            "finbert_score": finbert_score,
            "post_count": post_count,
            "hawk_dove_ref": hawk_dove_score,
            "ai_attribution": gemma_output.ai_attribution,
            "ai_analysis": gemma_output.ai_analysis,
            "tier_required": "FREE",
            "computed_at": now,
            "expires_at": now + timedelta(seconds=ml_settings.CACHE_TTL_COLD),
        }

    def _fallback_gemma_output(
        self,
        xgb_prob: float | None,
        rf_prob: float | None,
        finbert_score: float | None,
    ) -> GemmaSignalOutput:
        """ML-only signal when Gemma is unavailable."""
        ensemble = None
        if xgb_prob is not None and rf_prob is not None:
            ensemble = xgb_prob * 0.6 + rf_prob * 0.4
        elif xgb_prob is not None:
            ensemble = xgb_prob

        if ensemble is None:
            return GemmaSignalOutput(
                direction="NEUTRAL",
                confidence=0.5,
                holding_period="SHORT_TERM",
                ai_attribution="insufficient_model_data",
                ai_analysis="Models not available; no signal generated.",
            )

        # Sentiment nudge: FinBERT shifts the decision score ±0.02
        sent_nudge = 0.0
        if finbert_score is not None and abs(finbert_score) > 0.2:
            sent_nudge = finbert_score * 0.02

        score = ensemble + sent_nudge

        if score > 0.52:
            direction = "LONG"
        elif score < 0.48:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        confidence = round(min(1.0, max(0.5, abs(score - 0.5) * 4 + 0.5)), 4)

        drivers = []
        if ensemble is not None:
            drivers.append(f"ML ensemble {'bullish' if ensemble > 0.5 else 'bearish'}")
        if finbert_score is not None and abs(finbert_score) > 0.2:
            drivers.append(f"sentiment {'positive' if finbert_score > 0 else 'negative'}")
        attribution = " + ".join(drivers) if drivers else "ML ensemble"

        sentiment_note = f", FinBERT={finbert_score:.2f}" if finbert_score is not None else ""
        return GemmaSignalOutput(
            direction=direction,
            confidence=confidence,
            holding_period="SHORT_TERM",
            ai_attribution=attribution,
            ai_analysis=f"XGB={xgb_prob}, RF={rf_prob}{sentiment_note}. LLM reasoning unavailable.",
        )

    def _apply_macro_filter(
        self,
        direction: str,
        confidence: float,
        hawk_dove: float | None,
    ) -> tuple[str, float]:
        """Dampen LONG confidence when FOMC is strongly hawkish."""
        if hawk_dove is not None and hawk_dove > 0.5 and direction == "LONG":
            confidence = round(confidence * 0.85, 4)
            if confidence < ml_settings.MIN_CONFIDENCE_THRESHOLD:
                direction = "NEUTRAL"
        return direction, confidence

    def _neutral_signal(self, ticker: str, reason: str = "") -> dict:
        now = datetime.now(UTC)
        return {
            "ticker": ticker,
            "direction": "NEUTRAL",
            "confidence": 0.5,
            "holding_period": "SHORT_TERM",
            "xgb_prob_up": None,
            "rf_prob_up": None,
            "ensemble_prob": None,
            "finbert_score": None,
            "post_count": 0,
            "hawk_dove_ref": None,
            "ai_attribution": reason,
            "ai_analysis": "Insufficient data to generate a reliable signal.",
            "tier_required": "FREE",
            "computed_at": now,
            "expires_at": now + timedelta(hours=1),
        }

    async def _load_features(self, ticker: str, db_session) -> dict | None:
        """Latest model-ready feature row for `ticker` from the indicators_30min view.

        The view already exposes FEATURE_COLS (precomputed indicators + scale-free
        derivations) identical to what the trainer saw — no recomputation needed.
        """
        from sqlalchemy import text

        row = await db_session.execute(
            text(f"""
                SELECT {", ".join(FEATURE_COLS)}
                FROM indicators_30min
                WHERE ticker = :ticker
                ORDER BY time DESC
                LIMIT 1
            """),
            {"ticker": ticker},
        )
        mapping = row.mappings().first()
        return dict(mapping) if mapping is not None else None

    async def _get_celebrity_actions(self, ticker: str, db_session) -> list[dict]:
        from sqlalchemy import text

        rows = await db_session.execute(
            text("""
                SELECT celebrity, action, reported_at
                FROM celebrity_holdings
                WHERE ticker = :ticker
                ORDER BY reported_at DESC
                LIMIT 3
            """),
            {"ticker": ticker},
        )
        return [dict(r) for r in rows.mappings().all()]

    async def _get_latest_fomc(self, db_session) -> float | None:
        from sqlalchemy import text

        row = await db_session.execute(
            text("SELECT hawk_dove_score FROM fomc_statements ORDER BY time DESC LIMIT 1")
        )
        result = row.scalar_one_or_none()
        return float(result) if result is not None else None


signal_engine = SignalEngine()
