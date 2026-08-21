from agents import (
    AsyncOpenAI,
    OpenAIChatCompletionsModel,
    set_tracing_disabled,
)

from backend.config import get_settings

settings = get_settings()

# Required — otherwise the Agents SDK tries to send traces to OpenAI's
# platform and fails, since we're not using an OpenAI platform key.
set_tracing_disabled(True)

GEMINI_API_KEY = settings.gemini_api_key
MODEL_NAME = settings.gemini_model_name

# Gemini has no native OpenAI platform key, so it's accessed through its
# OpenAI-compatible endpoint.
external_client = AsyncOpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

# Gemini's compatibility layer only supports Chat Completions, not the
# Responses API — OpenAIChatCompletionsModel is required here.
gemini_model = OpenAIChatCompletionsModel(
    model=MODEL_NAME,
    openai_client=external_client,
)
