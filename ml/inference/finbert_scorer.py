"""
FinBERT sentiment scorer.
Loads ProsusAI/finbert (or fine-tuned checkpoint) and scores text batches.
Returns a float in [-1, 1]: positive=bullish, negative=bearish.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import torch
from transformers import pipeline

from ml.core.config import ml_settings

logger = logging.getLogger(__name__)

LABEL_TO_SCORE = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}


@dataclass
class SentimentResult:
    text: str
    label: str  # 'positive' | 'negative' | 'neutral'
    score: float  # probability of predicted label
    sentiment: float  # weighted score in [-1, 1]


@lru_cache(maxsize=1)
def _load_pipeline():
    logger.info("Loading FinBERT model: %s", ml_settings.FINBERT_MODEL)
    device = 0 if torch.cuda.is_available() else -1
    return pipeline(
        "text-classification",
        model=ml_settings.FINBERT_MODEL,
        tokenizer=ml_settings.FINBERT_MODEL,
        device=device,
        top_k=None,  # return all labels with probabilities
        truncation=True,
        max_length=ml_settings.FINBERT_MAX_LENGTH,
    )


class FinBERTScorer:
    def __init__(self):
        self._pipe = None  # lazy load on first use

    def _ensure_loaded(self):
        if self._pipe is None:
            self._pipe = _load_pipeline()

    def score(self, text: str) -> SentimentResult:
        """Score a single text snippet."""
        return self.score_batch([text])[0]

    def score_batch(self, texts: list[str]) -> list[SentimentResult]:
        """Score a list of texts. Returns one SentimentResult per text."""
        self._ensure_loaded()
        outputs = self._pipe(texts, batch_size=ml_settings.FINBERT_BATCH_SIZE)

        results = []
        for text, label_scores in zip(texts, outputs, strict=False):
            # label_scores is a list of {label, score} dicts (top_k=None)
            score_map = {item["label"].lower(): item["score"] for item in label_scores}
            best_label = max(score_map, key=score_map.get)
            best_prob = score_map[best_label]

            # Weighted sentiment: pos_prob - neg_prob
            weighted = score_map.get("positive", 0.0) - score_map.get("negative", 0.0)

            results.append(
                SentimentResult(
                    text=text,
                    label=best_label,
                    score=best_prob,
                    sentiment=round(weighted, 4),
                )
            )
        return results

    def aggregate_score(self, texts: list[str]) -> float | None:
        """Return mean weighted sentiment across a list of texts. Returns None if empty."""
        if not texts:
            return None
        results = self.score_batch(texts)
        return round(sum(r.sentiment for r in results) / len(results), 4)


# Module-level singleton
finbert_scorer = FinBERTScorer()
