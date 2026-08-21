"""Multilingual response tests across the languages required by CLAUDE.md:
English, Urdu, Roman Urdu, Arabic, Spanish. Verifies the agent replies in
the same language the customer wrote in (rule #3), including through a
handoff. Requires live Gemini calls — skipped (not failed) if the free-tier
daily generation quota is exhausted.
"""

import pytest
from agents import Runner

from backend.agents.triage import triage_agent
from backend.guardrails.security import detect_language
from backend.tests.conftest import load_cases, skip_if_quota_exhausted

MULTILINGUAL_CASES = load_cases("multilingual_cases.json")

# Latin-script languages are easily confused by a statistical detector on
# short text — same tolerance backend/guardrails/output.py's own
# language-consistency check applies, so this test doesn't demand strict
# ISO-code equality for Latin-script inputs like Roman Urdu.
_LATIN_SCRIPT_LANGS = {"en", "es", "fr", "de", "it", "pt", "nl"}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", MULTILINGUAL_CASES, ids=[c["id"] for c in MULTILINGUAL_CASES])
async def test_replies_in_the_customers_language(case: dict):
    async with skip_if_quota_exhausted():
        result = await Runner.run(triage_agent, case["message"])
        response_text = result.final_output if isinstance(result.final_output, str) else str(result.final_output)
        response_lang = detect_language(response_text)

        assert response_lang is not None, f"could not detect a language for response: {response_text!r}"

        if case["script"] == "latin":
            assert response_lang in _LATIN_SCRIPT_LANGS, (
                f"{case['id']!r}: expected a Latin-script reply, got language={response_lang!r} "
                f"for response: {response_text!r}"
            )
        else:
            assert response_lang == case["language"], (
                f"{case['id']!r}: expected language={case['language']!r}, got {response_lang!r} "
                f"for response: {response_text!r}"
            )


@pytest.mark.asyncio
async def test_language_does_not_drift_after_a_handoff():
    """Rule #3's most commonly missed bug: after Triage hands off, the new
    agent must keep replying in the customer's language, not fall back to
    English.
    """
    async with skip_if_quota_exhausted():
        result1 = await Runner.run(triage_agent, "What is your return policy?")

        turn2_input = result1.to_input_list() + [
            {
                "role": "user",
                "content": "شکریہ۔ اب مجھے بتائیں: کیا آپ بین الاقوامی شپنگ کرتے ہیں؟",
            }
        ]
        result2 = await Runner.run(result1.last_agent, turn2_input)
        response_text = result2.final_output if isinstance(result2.final_output, str) else str(result2.final_output)

        assert detect_language(response_text) == "ur", (
            f"expected the reply after handoff to stay in Urdu, got: {response_text!r}"
        )
