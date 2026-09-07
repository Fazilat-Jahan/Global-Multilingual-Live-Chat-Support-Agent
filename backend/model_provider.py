from agents import (
    AsyncOpenAI,
    ModelRetrySettings,
    ModelSettings,
    OpenAIChatCompletionsModel,
    RunConfig,
    retry_policies,
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
# OpenAI-compatible endpoint. An explicit timeout bounds how long a turn can
# hang if the network path to Gemini stalls (egress issue, black-holed
# connection) rather than failing fast with an HTTP error — the OpenAI SDK's
# default timeout is 10 minutes, far longer than a chat turn should ever
# wait, and a hang here produces no exception and nothing in the logs.
external_client = AsyncOpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    timeout=30.0,
)

# Gemini's compatibility layer only supports Chat Completions, not the
# Responses API — OpenAIChatCompletionsModel is required here.
gemini_model = OpenAIChatCompletionsModel(
    model=MODEL_NAME,
    openai_client=external_client,
)

# Gemini's OpenAI-compatible endpoint intermittently returns transient 5xx
# ("high demand") errors and connection drops. The Agents SDK's runner-managed
# retry is opt-in (agents/run_internal/model_retry.py returns retry=False
# whenever no policy is configured) — without this, a single transient
# failure surfaces straight to the customer as a generic error. This is
# applied via RunConfig at every Runner.run/run_streamed call site
# (backend/guardrails/runner.py) rather than per-agent, so it's defined once
# and covers every agent uniformly.
_RETRY_POLICY = retry_policies.any(
    retry_policies.provider_suggested(),
    retry_policies.network_error(),
    retry_policies.http_status([408, 429, 500, 502, 503, 504]),
)

DEFAULT_MODEL_SETTINGS = ModelSettings(
    retry=ModelRetrySettings(max_retries=3, policy=_RETRY_POLICY),
)

DEFAULT_RUN_CONFIG = RunConfig(model_settings=DEFAULT_MODEL_SETTINGS)
