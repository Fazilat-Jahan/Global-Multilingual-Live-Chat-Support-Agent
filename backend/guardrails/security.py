"""Shared, deterministic security checks used by the input/output guardrails.

These are intentionally heuristic/pattern-based rather than another LLM call:
guardrails are backend enforcement, not something we ask the model to police
itself (architecture principle — never let the LLM do what deterministic
backend code can enforce). A dedicated moderation API can replace the abuse
check later without changing the guardrail wiring.
"""

import re

from langdetect import DetectorFactory, LangDetectException, detect

# Make langdetect's output deterministic across runs.
DetectorFactory.seed = 0

MAX_INPUT_LENGTH = 4000

SAFE_BLOCKED_MESSAGE = (
    "I can't process that request. If you have a customer support question, "
    "I'm happy to help — or I can connect you with our human support team."
)

SAFE_ERROR_MESSAGE = (
    "Something went wrong on our end. Please try again in a moment, or ask "
    "to speak with a human and we'll follow up with you directly."
)

_PROMPT_INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"disregard (all |any )?(previous|prior|above)",
    r"reveal (your |the )?(system|hidden) prompt",
    r"(show|print|output|repeat) (your |the )?(system prompt|instructions)",
    r"what (are|were) your (system )?instructions",
    r"you are now (a|an|in) ",
    r"forget (all |any )?(previous|prior) instructions",
    r"act as (if |a |an )?(dan|jailbreak|unrestricted)",
    r"pretend (you have no|there are no) (restrictions|rules|guidelines)",
    r"bypass (your |the )?(guidelines|rules|restrictions|safety)",
    r"\bsystem\s*:\s*",
    r"\bassistant\s*:\s*.*\bignore\b",
]

_ABUSE_PATTERNS = [
    r"\bkill (yourself|you)\b",
    r"\bi will (hurt|kill) you\b",
    r"\bfuck (you|off)\b",
]

_UNSUPPORTED_REQUEST_PATTERNS = [
    r"write (me )?(a |an )?(poem|song|story|essay)\b",
    r"solve (this|the following) (math|equation)",
    r"generate (some |a )?(python|javascript|code)\b",
    r"tell me a joke",
    r"what('?s| is) the capital of\b",
]

# Internal details that must never reach a customer-facing response, per
# CLAUDE.md's error-handling rule (no tracebacks, keys, DB errors, URLs,
# system prompts).
_LEAKAGE_PATTERNS = [
    r"Traceback \(most recent call last\)",
    r"File \"[^\"]+\.py\"",
    r"\bTypeError\b|\bValueError\b|\bKeyError\b|\bAttributeError\b",
    r"postgresql(\+\w+)?://\S+",
    r"redis://\S+",
    r"\bqdrant://\S+|https?://localhost:\d+",
    r"\bAIza[0-9A-Za-z_\-]{20,}\b",
    r"\bsk-[A-Za-z0-9]{20,}\b",
    r"you are the (triage|rag|action|escalation) agent",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in patterns)


def check_prompt_injection(text: str) -> bool:
    return _matches_any(text, _PROMPT_INJECTION_PATTERNS)


def check_abusive_content(text: str) -> bool:
    return _matches_any(text, _ABUSE_PATTERNS)


def check_excessive_length(text: str) -> bool:
    return len(text) > MAX_INPUT_LENGTH


def check_unsupported_request(text: str) -> bool:
    return _matches_any(text, _UNSUPPORTED_REQUEST_PATTERNS)


def check_leaked_internals(text: str) -> bool:
    return _matches_any(text, _LEAKAGE_PATTERNS)


def detect_language(text: str) -> str | None:
    """Best-effort ISO 639-1 language code, or None if detection isn't
    reliable (e.g. text too short/ambiguous)."""
    cleaned = text.strip()
    if len(cleaned) < 4:
        return None
    try:
        return detect(cleaned)
    except LangDetectException:
        return None
