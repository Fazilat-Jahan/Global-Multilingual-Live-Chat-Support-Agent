import re

from agents import Agent, GuardrailFunctionOutput, RunContextWrapper, output_guardrail

from backend.guardrails.context import SupportContext
from backend.guardrails.security import (
    check_abusive_content,
    check_leaked_internals,
    detect_language,
)

# Latin-script languages we can't cleanly separate from a language-only
# statistical detector when the customer's own message is very short — used
# to avoid false positives (e.g. Roman Urdu / English / other Latin-script
# languages getting misclassified against each other).
_LATIN_SCRIPT_LANGS = {
    "en", "es", "fr", "de", "it", "pt", "nl", "id", "so", "tl", "sw", "cy", "da", "sv", "no",
}

_EXPLICIT_LANGUAGE_REQUEST_PATTERN = re.compile(
    r"\b(in|reply in|answer in|respond in|use)\s+(english|urdu|arabic|spanish|french|roman urdu)\b",
    re.IGNORECASE,
)


def _is_language_mismatch(user_text: str, agent_text: str) -> bool:
    if _EXPLICIT_LANGUAGE_REQUEST_PATTERN.search(user_text):
        # Customer explicitly asked for a specific language — not a drift.
        return False

    user_lang = detect_language(user_text)
    agent_lang = detect_language(agent_text)
    if user_lang is None or agent_lang is None or user_lang == agent_lang:
        return False

    # Both Latin-script languages are frequently confused by statistical
    # detectors on short text (e.g. Roman Urdu vs. English) — only trust a
    # mismatch here when at least one side is unambiguously non-Latin-script
    # (Urdu/Arabic script, CJK, Devanagari, etc.), since that's the failure
    # mode this check exists to catch.
    if user_lang in _LATIN_SCRIPT_LANGS and agent_lang in _LATIN_SCRIPT_LANGS:
        return False

    return True


@output_guardrail
async def validate_agent_output(
    ctx: RunContextWrapper[SupportContext], agent: Agent, agent_output
) -> GuardrailFunctionOutput:
    """Runs on the final agent output before it's returned to the customer:
    safety, language consistency, and sensitive-info leakage. Internal
    failures never leak here — see backend/guardrails/security.py for the
    exact patterns blocked.
    """
    text = agent_output if isinstance(agent_output, str) else str(agent_output)

    if check_leaked_internals(text):
        return GuardrailFunctionOutput(
            output_info={"reason": "internal_leakage"},
            tripwire_triggered=True,
        )

    if check_abusive_content(text):
        return GuardrailFunctionOutput(
            output_info={"reason": "unsafe_output"},
            tripwire_triggered=True,
        )

    user_text = ctx.context.latest_user_message if ctx.context else ""
    if user_text and _is_language_mismatch(user_text, text):
        return GuardrailFunctionOutput(
            output_info={
                "reason": "language_mismatch",
                "expected_language": detect_language(user_text),
            },
            tripwire_triggered=True,
        )

    return GuardrailFunctionOutput(output_info={"reason": None}, tripwire_triggered=False)
