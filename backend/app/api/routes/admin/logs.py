from __future__ import annotations

import collections
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_tier

router = APIRouter()
AdminUser = Depends(require_tier("ADMIN"))


class AdminLogBuffer(logging.Handler):
    """In-memory ring buffer that captures log records for the admin dashboard."""

    def __init__(self, capacity: int = 2000):
        super().__init__()
        self._buffer: collections.deque[dict] = collections.deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._buffer.append(
                {
                    "timestamp": datetime.fromtimestamp(
                        record.created, tz=UTC
                    ).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": self.format(record),
                }
            )
        except Exception:
            self.handleError(record)

    def tail(
        self, n: int = 100, min_level: str = "INFO"
    ) -> list[dict]:
        level_num = getattr(logging, min_level.upper(), logging.INFO)
        entries = [
            entry
            for entry in reversed(self._buffer)
            if getattr(logging, entry["level"], 0) >= level_num
        ]
        return entries[:n]

    @property
    def size(self) -> int:
        return len(self._buffer)


_log_buffer: AdminLogBuffer | None = None


def init_log_buffer() -> AdminLogBuffer:
    """Create and attach the log buffer to the root logger. Call once at startup."""
    global _log_buffer
    if _log_buffer is not None:
        return _log_buffer
    _log_buffer = AdminLogBuffer(capacity=2000)
    _log_buffer.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(_log_buffer)
    return _log_buffer


def get_log_buffer() -> AdminLogBuffer | None:
    return _log_buffer


@router.get("/logs")
async def system_logs(
    _=AdminUser,
    lines: int = Query(100, ge=1, le=1000),
    level: str = Query("INFO"),
):
    """Tail recent application logs from the in-memory buffer."""
    buf = get_log_buffer()
    if buf is None:
        return {"entries": [], "total_buffered": 0, "showing": 0, "min_level": level}

    entries = buf.tail(n=lines, min_level=level)
    return {
        "entries": entries,
        "total_buffered": buf.size,
        "showing": len(entries),
        "min_level": level.upper(),
    }
