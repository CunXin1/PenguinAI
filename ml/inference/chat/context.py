"""Per-request scope for a chat turn.

SECURITY INVARIANT: `user_id` is set server-side from the authenticated token and
is the ONLY source of user identity for tools. It is NEVER read from model-provided
tool arguments — so a user (or a prompt injection) can never reach another user's
watchlist/portfolio. Tools that need a user read it from here, not from their args.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ChatContext:
    user_id: str | None  # UUID from auth token; None for guest (user-scoped tools refuse)
    tier: str = "FREE"  # FREE | PRO | PREMIUM | ADMIN
    db: Any = None  # AsyncSession handed to tool handlers (None → DB tools unavailable)
    focus_ticker: str | None = None  # ticker the chat UI is focused on, if any
