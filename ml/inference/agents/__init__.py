"""SDK-based PREMIUM chat agent (OpenAI Agents SDK).

A drop-in alternative to ml.inference.chat (the hand-rolled tool loop), selected by
``ml_settings.CHAT_AGENT_SDK``. Shares the ChatContext security model and the same
read-only handlers; differs only in the agent harness (Agents SDK) and transport
(OpenAI-compatible client over our vLLM/Ollama endpoints). See CLAUDE.md → "LLM Chat Agent".
"""

from ml.inference.agents.runner import run, run_stream

__all__ = ["run", "run_stream"]
