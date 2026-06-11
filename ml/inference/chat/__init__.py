"""PREMIUM chat agent — conversational, tool-calling, per-user.

Separate surface from the signal pipeline (ml/inference/gemma_agent.py); shares
only the LLM backend layer. See CLAUDE.md → "LLM Chat Agent".
"""

from ml.inference.chat.agent import ChatAgent, chat_agent
from ml.inference.chat.context import ChatContext
from ml.inference.chat.tools import Tool, ToolRegistry, build_default_registry

__all__ = [
    "ChatAgent",
    "ChatContext",
    "Tool",
    "ToolRegistry",
    "build_default_registry",
    "chat_agent",
]
