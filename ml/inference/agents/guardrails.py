"""Compliance output guardrail — financial-advice safety net.

PenguinAI gives signals/research, never personalized advice. The PRIMARY enforcement
is the system prompt (the model is told to explain both sides and append a disclaimer).
This guardrail is a SECONDARY, deterministic net: it inspects the final answer and flags
advice-like phrasing that lacks a disclaimer.

It is intentionally NON-blocking (``tripwire_triggered=False``): the answer has already
streamed to the user token-by-token, so raising would not unsend it — instead we record a
compliance flag for logging/monitoring. The disclaimer itself is produced by the model.
"""

from __future__ import annotations

import logging
import re

from agents import Agent, GuardrailFunctionOutput, RunContextWrapper, output_guardrail

from ml.inference.chat.context import ChatContext

logger = logging.getLogger(__name__)

# Imperative buy/sell direction aimed at the user — the thing we must not do.
_ADVICE_RE = re.compile(
    r"\b(you should (buy|sell|short)|i('| a)?m? recommend(ing)? (buying|selling)|"
    r"guaranteed|definitely (buy|sell)|can'?t lose|sure thing|you must (buy|sell))\b",
    re.IGNORECASE,
)
# Any acknowledgement that this is not personalized advice. "not ... advice" tolerates a
# few words between (e.g. "not personalized financial advice", "not investment advice").
_DISCLAIMER_RE = re.compile(
    r"\bnot\s+(?:[\w-]+\s+){0,3}advice\b|informational purposes|consult\s+(?:a|your|with)\b.*advisor",
    re.IGNORECASE,
)


def assess_compliance(text: str) -> dict:
    """Deterministic check: does the answer give imperative advice without a disclaimer?"""
    advice_language = bool(_ADVICE_RE.search(text))
    has_disclaimer = bool(_DISCLAIMER_RE.search(text))
    return {
        "advice_language": advice_language,
        "has_disclaimer": has_disclaimer,
        "flagged": advice_language and not has_disclaimer,
    }


@output_guardrail
async def compliance_guardrail(
    ctx: RunContextWrapper[ChatContext], agent: Agent, output: str
) -> GuardrailFunctionOutput:
    info = assess_compliance(output if isinstance(output, str) else str(output))
    if info["flagged"]:
        logger.warning("compliance guardrail: advice-like output without a disclaimer")
    return GuardrailFunctionOutput(
        output_info=info,
        tripwire_triggered=False,  # advisory only — never break the user's streamed answer
    )
