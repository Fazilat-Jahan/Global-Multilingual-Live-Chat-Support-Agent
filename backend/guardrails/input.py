from agents import Agent, GuardrailFunctionOutput, RunContextWrapper, TResponseInputItem, input_guardrail

from backend.guardrails.context import SupportContext
from backend.guardrails.security import (
    SAFE_BLOCKED_MESSAGE,
    check_abusive_content,
    check_excessive_length,
    check_prompt_injection,
    check_unsupported_request,
)


def _latest_text(input: str | list[TResponseInputItem]) -> str:
    if isinstance(input, str):
        return input
    for item in reversed(input):
        content = item.get("content") if isinstance(item, dict) else None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for part in content:
                text = part.get("text") if isinstance(part, dict) else None
                if text:
                    return text
    return ""


@input_guardrail(run_in_parallel=False)
async def validate_customer_input(
    ctx: RunContextWrapper[SupportContext], agent: Agent, input: str | list[TResponseInputItem]
) -> GuardrailFunctionOutput:
    """Runs before the agent processes each customer message: prompt-injection
    detection, abuse/malicious content, excessive length, and unsupported
    (clearly off-topic) requests. Blocks unsafe input before any agent logic
    or tool runs.
    """
    text = _latest_text(input)

    if check_excessive_length(text):
        return GuardrailFunctionOutput(
            output_info={"reason": "excessive_length", "safe_message": SAFE_BLOCKED_MESSAGE},
            tripwire_triggered=True,
        )

    if check_prompt_injection(text):
        return GuardrailFunctionOutput(
            output_info={"reason": "prompt_injection", "safe_message": SAFE_BLOCKED_MESSAGE},
            tripwire_triggered=True,
        )

    if check_abusive_content(text):
        return GuardrailFunctionOutput(
            output_info={"reason": "abusive_content", "safe_message": SAFE_BLOCKED_MESSAGE},
            tripwire_triggered=True,
        )

    if check_unsupported_request(text):
        return GuardrailFunctionOutput(
            output_info={
                "reason": "unsupported_request",
                "safe_message": (
                    "I'm a customer support assistant, so I can only help with orders, "
                    "policies, products, and account questions. How can I help with that?"
                ),
            },
            tripwire_triggered=True,
        )

    return GuardrailFunctionOutput(output_info={"reason": None}, tripwire_triggered=False)
