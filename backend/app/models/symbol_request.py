from sqlalchemy import Column, DateTime, Integer, Text, func

from app.core.database import Base


class SymbolRequest(Base):
    """A user-requested symbol that is not (yet) in our coverage universe.

    Searching for an uncovered symbol records a row here; a background job
    validates it against Massive and sets ``status``. This doubles as a
    data-demand queue — the most-requested missing symbols bubble up.
    """

    __tablename__ = "symbol_requests"

    symbol = Column(Text, primary_key=True)
    request_count = Column(Integer, nullable=False, default=1)
    status = Column(Text, nullable=False, default="pending")
    # pending | real_pending_ingest | delisted | rejected_junk | ingested
    resolved_name = Column(Text)
    resolved_exchange = Column(Text)
    note = Column(Text)
    first_requested_at = Column(DateTime(timezone=True), server_default=func.now())
    last_requested_at = Column(DateTime(timezone=True), server_default=func.now())
    validated_at = Column(DateTime(timezone=True))
