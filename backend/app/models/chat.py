"""SQLAlchemy models for the LLM Chat Agent's per-user conversation history.

Tables are created by db/schema/03_relational.sql (db-init); these models map to
them for ORM access. A conversation is owned by a user (cascade delete); messages
belong to a conversation (cascade delete).
"""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = Column(Text, nullable=False, default="New chat")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    messages = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(Text, nullable=False)  # 'user' | 'assistant'
    content = Column(Text, nullable=False)
    tools_used = Column(ARRAY(Text), nullable=False, default=list)
    # JSONB in Postgres (prod); generic JSON on SQLite (tests) — same Python value.
    cards = Column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )  # rich UI cards (chart/news) for this turn; None = none
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("ChatConversation", back_populates="messages")
