from sqlalchemy import Column, DateTime, Integer, Numeric, Text, func

from app.core.database import Base


class SignalCache(Base):
    __tablename__ = "signal_cache"

    ticker = Column(Text, primary_key=True)
    direction = Column(Text, nullable=False)          # LONG | SHORT | NEUTRAL
    confidence = Column(Numeric(5, 4), nullable=False)
    holding_period = Column(Text, nullable=False)     # INTRADAY | SHORT_TERM | SWING | POSITION

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
