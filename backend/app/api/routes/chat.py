"""Chat assistant endpoints.

Stateless (legacy):
    POST /api/chat                              — send a conversation, get one reply
    GET  /api/chat/quota                        — current per-user quota snapshot

Per-user conversation history (tool-calling agent):
    GET    /api/chat/conversations              — list the caller's threads
    POST   /api/chat/conversations              — create an empty thread
    GET    /api/chat/conversations/{id}         — a thread + its messages
    DELETE /api/chat/conversations/{id}         — delete a thread
    POST   /api/chat/conversations/{id}/messages — send a user turn, persist + reply

Chat is gated behind login so usage is metered per user (see ``core/chat_limit``).
User free-text reaches the LLM here and ONLY here; the system prompt + tools are
assembled server-side (``ml.inference.chat``) and are never client-controllable.
The agent's tools are READ-ONLY and scoped to the authenticated user.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.chat_limit import consume_quota, peek_quota, refund_quota
from app.core.config import settings
from app.core.database import get_db
from app.models.chat import ChatConversation, ChatMessage
from app.schemas.chat import (
    ChatReply,
    ChatRequest,
    ChatUsage,
    ConversationDetail,
    ConversationOut,
    MessageOut,
    SendMessageReply,
    SendMessageRequest,
)
from app.services.chat_agent import ChatAgentUnavailable, run_chat_agent
from app.services.chat_llm import ChatUnavailable, complete_chat

logger = logging.getLogger(__name__)
router = APIRouter()


def _ensure_enabled() -> None:
    if not settings.CHAT_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The chat assistant is currently disabled.",
        )


def _title_from(text: str) -> str:
    """First line of the first user message, truncated — used as the thread title."""
    line = text.strip().splitlines()[0] if text.strip() else "New chat"
    return (line[:57] + "…") if len(line) > 58 else line


# ── Quota + legacy stateless chat ─────────────────────────────────────────────
@router.get("/quota", response_model=ChatUsage)
async def chat_quota(user: CurrentUser) -> ChatUsage:
    """Report the caller's remaining chat allowance without consuming any."""
    _ensure_enabled()
    return ChatUsage(**await peek_quota(user))


@router.post("", response_model=ChatReply)
async def chat(req: ChatRequest, user: CurrentUser) -> ChatReply:
    """Generate one assistant reply for the supplied conversation (stateless)."""
    _ensure_enabled()

    # Meter first: a rejected request must never reach the model (raises 429).
    usage = await consume_quota(user)

    history = [m.model_dump() for m in req.messages]
    try:
        reply = await complete_chat(history)
    except ChatUnavailable as e:
        await refund_quota(user)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e

    return ChatReply(reply=reply, usage=ChatUsage(**usage))


# ── Conversation history ──────────────────────────────────────────────────────
async def _owned_conversation(
    conversation_id: UUID, user: CurrentUser, db: AsyncSession
) -> ChatConversation:
    """Load a conversation, 404 unless it belongs to the caller (tenant isolation)."""
    conv = (
        await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conv


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[ChatConversation]:
    """The caller's conversations, most recently updated first."""
    _ensure_enabled()
    rows = (
        await db.execute(
            select(ChatConversation)
            .where(ChatConversation.user_id == user.id)
            .order_by(ChatConversation.updated_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return list(rows)


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> ChatConversation:
    """Start a new empty conversation."""
    _ensure_enabled()
    conv = ChatConversation(user_id=user.id, title="New chat")
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return conv


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> ChatConversation:
    """A conversation with its full message history (oldest first)."""
    _ensure_enabled()
    conv = await _owned_conversation(conversation_id, user, db)
    await db.refresh(conv, attribute_names=["messages"])
    return conv


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    """Delete a conversation and its messages (cascade)."""
    _ensure_enabled()
    await _owned_conversation(conversation_id, user, db)  # 404 if not owner
    await db.execute(delete(ChatConversation).where(ChatConversation.id == conversation_id))


@router.post("/conversations/{conversation_id}/messages", response_model=SendMessageReply)
async def send_message(
    conversation_id: UUID,
    req: SendMessageRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SendMessageReply:
    """Add a user turn, run the tool-calling agent, persist + return the reply."""
    _ensure_enabled()
    conv = await _owned_conversation(conversation_id, user, db)

    # Meter first: a rejected request must never reach the model (raises 429).
    usage = await consume_quota(user)

    # Prior turns become the agent's history (the new user message is added by the agent).
    prior = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conv.id)
            .order_by(ChatMessage.created_at)
            .limit(settings.CHAT_MAX_HISTORY)
        )
    ).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in prior]

    try:
        reply_text, tools_used = await run_chat_agent(
            user_message=req.content,
            user_id=user.id,
            tier=user.tier,
            db=db,
            history=history,
            focus_ticker=req.focus_ticker,
        )
    except ChatAgentUnavailable as e:
        # A server-side failure shouldn't cost the user a message or persist a turn.
        await refund_quota(user)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e

    # Persist both turns together; auto-title the thread on its first message.
    db.add(ChatMessage(conversation_id=conv.id, role="user", content=req.content))
    assistant_msg = ChatMessage(
        conversation_id=conv.id,
        role="assistant",
        content=reply_text,
        tools_used=tools_used or [],
    )
    db.add(assistant_msg)
    if not prior:
        conv.title = _title_from(req.content)
    conv.updated_at = func.now()
    await db.flush()
    await db.refresh(assistant_msg)

    return SendMessageReply(
        message=MessageOut.model_validate(assistant_msg),
        conversation_id=conv.id,
        title=conv.title,
        usage=ChatUsage(**usage),
    )
