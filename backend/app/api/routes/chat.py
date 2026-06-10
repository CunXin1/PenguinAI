"""Chat assistant endpoints.

    POST /api/chat        — send the conversation, get one assistant reply
    GET  /api/chat/quota  — current per-user quota snapshot

Chat is gated behind login so usage can be metered per user (see
``core/chat_limit``). User free-text reaches the LLM here and ONLY here; the
system prompt is assembled server-side (``services/chat_llm``) and is never
client-controllable.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser
from app.core.chat_limit import consume_quota, peek_quota, refund_quota
from app.core.config import settings
from app.schemas.chat import ChatReply, ChatRequest, ChatUsage
from app.services.chat_llm import ChatUnavailable, complete_chat

logger = logging.getLogger(__name__)
router = APIRouter()


def _ensure_enabled() -> None:
    if not settings.CHAT_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The chat assistant is currently disabled.",
        )


@router.get("/quota", response_model=ChatUsage)
async def chat_quota(user: CurrentUser) -> ChatUsage:
    """Report the caller's remaining chat allowance without consuming any."""
    _ensure_enabled()
    return ChatUsage(**await peek_quota(user))


@router.post("", response_model=ChatReply)
async def chat(req: ChatRequest, user: CurrentUser) -> ChatReply:
    """Generate one assistant reply for the supplied conversation."""
    _ensure_enabled()

    # Meter first: a rejected request must never reach the model (raises 429).
    usage = await consume_quota(user)

    history = [m.model_dump() for m in req.messages]
    try:
        reply = await complete_chat(history)
    except ChatUnavailable as e:
        # A server-side failure shouldn't cost the user a message.
        await refund_quota(user)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e

    return ChatReply(reply=reply, usage=ChatUsage(**usage))
