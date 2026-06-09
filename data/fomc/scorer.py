"""FOMC hawk/dove scorer using FinBERT.

Splits a statement into paragraph-sized chunks, scores each with FinBERT,
then maps the financial-sentiment output onto a hawk/dove axis:

  - "positive" (FinBERT) → economy is strong → hawkish (+)
  - "negative" (FinBERT) → economy is weak → dovish (−)
  - "neutral"  → 0

The final score is the mean across all chunks, in [−1, +1].

Keyword-based adjustments boost accuracy on FOMC-specific language that
FinBERT (trained on general financial news) may misjudge — e.g. "rate hike"
is hawkish even if the surrounding tone is neutral.

RUN (standalone test):
    python -m data.fomc.scorer
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("fomc_scorer")

HAWK_PHRASES = [
    "rate increase", "rate hike", "raising rates", "tightening",
    "quantitative tightening", "reduce the size of",
    "inflation remains elevated", "inflation is high",
    "price stability", "restrictive stance",
    "strong labor market", "robust employment",
    "further increases", "additional firming",
]

DOVE_PHRASES = [
    "rate cut", "rate reduction", "lowering rates", "easing",
    "quantitative easing", "increase the size of",
    "economic slowdown", "recession", "downside risks",
    "accommodative stance", "support the economy",
    "below maximum employment", "weak labor market",
    "further decline", "deterioration",
]

HAWK_BOOST = 0.10
DOVE_BOOST = -0.10


@dataclass
class ChunkScore:
    text: str
    finbert_sentiment: float  # [-1, 1] from FinBERT
    keyword_adj: float  # hawk/dove keyword adjustment
    final: float  # finbert_sentiment + keyword_adj, clamped to [-1, 1]


@dataclass
class StatementScore:
    hawk_dove_score: float  # mean across chunks, [-1, 1]
    chunk_scores: list[ChunkScore]
    summary: str  # auto-generated one-liner


def _chunk_text(text: str, max_tokens: int = 400) -> list[str]:
    """Split text into chunks of roughly max_tokens words, on paragraph boundaries."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para.split())
        if current and current_len + para_len > max_tokens:
            chunks.append("\n".join(current))
            current = [para]
            current_len = para_len
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n".join(current))

    return chunks


def _keyword_adjustment(text: str) -> float:
    lower = text.lower()
    hawk_hits = sum(1 for p in HAWK_PHRASES if p in lower)
    dove_hits = sum(1 for p in DOVE_PHRASES if p in lower)
    return (hawk_hits * HAWK_BOOST) + (dove_hits * DOVE_BOOST)


def _generate_summary(score: float, text: str) -> str:
    lower = text.lower()

    rate_match = re.search(
        r"(?:target range|federal funds rate).*?(\d[\d./\- to]+\s*(?:percent|%))",
        lower,
    )
    rate_info = ""
    if rate_match:
        rate_info = f" Rate: {rate_match.group(1).strip()}."

    if score >= 0.3:
        stance = "Hawkish"
    elif score >= 0.1:
        stance = "Slightly hawkish"
    elif score > -0.1:
        stance = "Neutral"
    elif score > -0.3:
        stance = "Slightly dovish"
    else:
        stance = "Dovish"

    return f"{stance} ({score:+.2f}).{rate_info}"


def score_statement(text: str) -> StatementScore:
    """Score a full FOMC statement for hawk/dove sentiment using FinBERT.

    Lazy-imports FinBERT so the module can be imported without torch installed
    (e.g. for tests or type-checking).
    """
    from ml.inference.finbert_scorer import finbert_scorer

    chunks = _chunk_text(text)
    if not chunks:
        return StatementScore(
            hawk_dove_score=0.0,
            chunk_scores=[],
            summary="No scoreable text.",
        )

    finbert_results = finbert_scorer.score_batch(chunks)

    chunk_scores: list[ChunkScore] = []
    for chunk_text, fb_result in zip(chunks, finbert_results, strict=True):
        kw_adj = _keyword_adjustment(chunk_text)
        raw = fb_result.sentiment + kw_adj
        final = max(-1.0, min(1.0, raw))
        chunk_scores.append(ChunkScore(
            text=chunk_text[:200],
            finbert_sentiment=fb_result.sentiment,
            keyword_adj=round(kw_adj, 4),
            final=round(final, 4),
        ))

    mean_score = sum(c.final for c in chunk_scores) / len(chunk_scores)
    mean_score = round(max(-1.0, min(1.0, mean_score)), 4)

    summary = _generate_summary(mean_score, text)

    return StatementScore(
        hawk_dove_score=mean_score,
        chunk_scores=chunk_scores,
        summary=summary,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    sample = (
        "Recent indicators suggest that economic activity has continued to expand "
        "at a solid pace. The unemployment rate has stabilized at a low level in "
        "recent months, and labor market conditions remain solid. Inflation remains "
        "somewhat elevated.\n"
        "The Committee decided to maintain the target range for the federal funds "
        "rate at 4-1/4 to 4-1/2 percent."
    )
    result = score_statement(sample)
    print(f"Score: {result.hawk_dove_score:+.4f}")
    print(f"Summary: {result.summary}")
    for i, c in enumerate(result.chunk_scores):
        print(f"  chunk {i}: finbert={c.finbert_sentiment:+.4f} kw={c.keyword_adj:+.4f} → {c.final:+.4f}")
