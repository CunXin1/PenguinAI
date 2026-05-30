from sqlalchemy import Boolean, Column, BigInteger, Date, DateTime, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
import uuid

from app.core.database import Base


class Ticker(Base):
    __tablename__ = "tickers"

    ticker = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    exchange = Column(Text, nullable=True)
    sector = Column(Text, nullable=True)
    industry = Column(Text, nullable=True)
    market_cap = Column(BigInteger, nullable=True)
    tags = Column(ARRAY(Text), default=list)
    is_active = Column(Boolean, nullable=False, default=True)
    data_start = Column(Date, nullable=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())
