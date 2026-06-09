from sqlalchemy import Boolean, Column, DateTime, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ARRAY

from app.core.database import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Text, primary_key=True)  # source_provider:source_id
    source_provider = Column(Text, nullable=False)
    source_id = Column(Text, nullable=False)
    headline = Column(Text, nullable=False)
    summary = Column(Text)
    article_url = Column(Text)
    image_url = Column(Text)
    author = Column(Text)
    publisher_name = Column(Text)
    published_at = Column(DateTime(timezone=True), nullable=False)
    tickers = Column(ARRAY(Text), default=list)
    category = Column(Text, default="general")
    sentiment = Column(Text)  # positive | negative | neutral
    sentiment_score = Column(Numeric(5, 4))
    sentiment_reasoning = Column(Text)
    is_hot = Column(Boolean, nullable=False, default=False)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
