import uuid

from sqlalchemy import Boolean, Column, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(Text, unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=True)
    display_name = Column(Text, nullable=True)
    oauth_provider = Column(String(20), nullable=True)  # 'google' | 'apple' | None
    oauth_sub = Column(Text, nullable=True)
    tier = Column(String(20), nullable=False, default="FREE")  # FREE | PRO | PREMIUM | ADMIN
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
