from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class MLScores(BaseModel):
    xgb_prob_up: float | None = None
    rf_prob_up: float | None = None
    ensemble_prob: float | None = None


class SentimentInfo(BaseModel):
    finbert_score: float | None = None
    post_count: int | None = None
    hawk_dove_ref: float | None = None


class SignalResponse(BaseModel):
    ticker: str
    direction: Literal["LONG", "SHORT", "NEUTRAL"]
    confidence: float = Field(ge=0.0, le=1.0)
    holding_period: Literal["INTRADAY", "SHORT_TERM", "SWING", "POSITION"]
    ml_scores: MLScores
    sentiment: SentimentInfo
    ai_attribution: str | None = None
    ai_analysis: str | None = None
    tier_required: Literal["FREE", "PRO", "PREMIUM"] = "FREE"
    computed_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}


class SignalListItem(BaseModel):
    ticker: str
    direction: Literal["LONG", "SHORT", "NEUTRAL"]
    confidence: float
    holding_period: str
    computed_at: datetime

    model_config = {"from_attributes": True}
