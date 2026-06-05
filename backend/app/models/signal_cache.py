from sqlalchemy import Column, DateTime, Integer, Numeric, Text, func

from app.core.database import Base


class SignalCache(Base):
    __tablename__ = "signal_cache"

    ticker = Column(Text, primary_key=True)
    direction = Column(Text, nullable=False)  # LONG | SHORT | NEUTRAL
    confidence = Column(Numeric(5, 4), nullable=False)
    holding_period = Column(Text, nullable=False)  # INTRADAY | SHORT_TERM | SWING | POSITION

    # ML scores
    xgb_prob_up = Column(Numeric(5, 4))
    rf_prob_up = Column(Numeric(5, 4))
    ensemble_prob = Column(Numeric(5, 4))

    # Sentiment
    finbert_score = Column(Numeric(5, 4))
    post_count = Column(Integer)
    hawk_dove_ref = Column(Numeric(5, 4))

    # AI output
    ai_attribution = Column(Text)
    ai_analysis = Column(Text)

    # Meta
    tier_required = Column(Text, nullable=False, default="FREE")
    computed_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)

    @property
    def ml_scores(self) -> dict:
        return {
            "xgb_prob_up": self.xgb_prob_up,
            "rf_prob_up": self.rf_prob_up,
            "ensemble_prob": self.ensemble_prob,
        }

    @property
    def sentiment(self) -> dict:
        return {
            "finbert_score": self.finbert_score,
            "post_count": self.post_count,
            "hawk_dove_ref": self.hawk_dove_ref,
        }
