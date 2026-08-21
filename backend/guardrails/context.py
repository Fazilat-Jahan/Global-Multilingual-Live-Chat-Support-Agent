from dataclasses import dataclass


@dataclass
class SupportContext:
    """Custom run context passed to every Runner.run() call. Guardrails and
    tools read this via RunContextWrapper.context / ToolContext.context — it
    is never sent to the LLM, only used by our own backend code.
    """

    session_id: str
    customer_id: str | None = None
    # Set by conversation_service once the conversation row is loaded/created,
    # so tools (e.g. create_support_ticket) can attach DB writes to the right
    # conversation without the LLM ever having to know/pass a DB id.
    conversation_id: str | None = None
    # Set by the orchestration layer (backend.guardrails.runner) before each
    # turn, so guardrails can compare the user's current-turn language
    # against the agent's response language.
    latest_user_message: str = ""
