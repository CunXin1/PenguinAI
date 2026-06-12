"""Per-request scope for a chat turn.

SECURITY INVARIANT: `user_id` is set server-side from the authenticated token and
is the ONLY source of user identity for tools. It is NEVER read from model-provided
tool arguments — so a user (or a prompt injection) can never reach another user's
watchlist/portfolio. Tools that need a user read it from here, not from their args.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatContext:
    user_id: str | None  # UUID from auth token; None for guest (user-scoped tools refuse)
    tier: str = "FREE"  # FREE | PRO | PREMIUM | ADMIN
    db: Any = None  # AsyncSession handed to tool handlers (None → DB tools unavailable)
    focus_ticker: str | None = None  # ticker the chat UI is focused on, if any
    # SDK chat-agent side-channel: tools append rich-card payloads here
    # ({"card": "chart"|"news", "data": {...}}); the runner drains + streams them.
    # Left None by the hand-rolled agent, which doesn't emit cards.
    card_sink: list[dict] | None = field(default=None)
    # Serializes DB access across tools. The SDK may run several tool calls in one
    # turn CONCURRENTLY, but a single AsyncSession forbids concurrent operations —
    # this lock makes the shared session safe without giving up the request scope.
    db_lock: Any = field(default_factory=asyncio.Lock, repr=False, compare=False)
