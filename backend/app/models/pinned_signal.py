from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class PinnedSignal(Base):
    __tablename__ = "pinned_signals"

    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    ticker = Column(Text, ForeignKey("tickers.ticker", ondelete="CASCADE"), primary_key=True)
    position = Column(Integer, nullable=False, default=0)
