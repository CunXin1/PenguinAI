"""Pydantic models for the user-facing chat assistant.

Chat is the ONE place user free-text reaches an LLM (the signal-generation
pipeline never does — its prompts stay 100% backend-assembled). To keep the
injection surface minimal even here:

  * the client may send only ``user`` / ``assistant`` turns — the system prompt
    is assembled server-side (see ``services/chat_llm.py``) and can never be
    supplied or overridden by the client;
  * every turn is length-capped and the history depth is bounded.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


class ChatTurn(BaseModel):
    """One conversation turn supplied by the client as context."""

    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def _validate_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message content cannot be empty")
        if len(v) > settings.CHAT_MAX_INPUT_CHARS:
            raise ValueError(f"Message too long (max {settings.CHAT_MAX_INPUT_CHARS} characters)")
        return v


class ChatRequest(BaseModel):
    # Bounded depth: a malicious client can't push unlimited context.
    messages: list[ChatTurn] = Field(min_length=1, max_length=settings.CHAT_MAX_HISTORY)

    @field_validator("messages")
    @classmethod
    def _last_turn_is_user(cls, v: list[ChatTurn]) -> list[ChatTurn]:
        if v[-1].role != "user":
            raise ValueError("The last message must be from the user")
        return v


class ChatUsage(BaseModel):
    """Quota snapshot returned with every reply and from GET /api/chat/quota."""

    tier: str
    limit: int  # messages allowed per window; 0 = unlimited
    remaining: int  # remaining in the current window; -1 = unlimited
    reset_seconds: int  # seconds until the window resets (0 if window not started)
    window_seconds: int  # length of the quota window


class ChatReply(BaseModel):
    reply: str
    usage: ChatUsage
