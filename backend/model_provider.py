import logging
import time

import httpx
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
from backend.observability import metrics

settings = get_settings()
logger = logging.getLogger(__name__)

# Required — otherwise the Agents SDK tries to send traces to OpenAI's
# platform and fails, since we're not using an OpenAI platform key.
set_tracing_disabled(True)

GEMINI_API_KEY = settings.gemini_api_key
MODEL_NAME = settings.gemini_model_name

_START_TIME_EXTENSION_KEY = "traced_request_start"


def build_traced_http_client(label: str, timeout_seconds: float) -> httpx.AsyncClient:
    """An httpx.AsyncClient with request/response logging hooks, for every
    outbound call to Gemini's OpenAI-compatible endpoint.

    This exists because the OpenAI SDK's own retry/streaming machinery
    (agents.Runner.run_streamed) makes an unknown number of HTTP calls per
    turn (initial call, per-handoff, per-tool-continuation, per-retry) with
    zero visibility from our side otherwise — a client-level `timeout` bounds
    how long any single call can hang, but doesn't tell us WHICH call, or
    whether the request was even sent vs. still waiting on a response. The
    "response" hook fires once headers are received (not once the full body/
    stream is read), so a request logged with no matching response log
    pinpoints the network round-trip itself as the stall point rather than
    something in our own code before or after it.
    """

    async def _log_request(request: httpx.Request) -> None:
        request.extensions[_START_TIME_EXTENSION_KEY] = time.monotonic()
        logger.info("[%s] HTTP request started: %s %s", label, request.method, request.url.path)

    async def _log_response(response: httpx.Response) -> None:
        start = response.request.extensions.get(_START_TIME_EXTENSION_KEY)
        duration = time.monotonic() - start if start is not None else None
        elapsed = f"{duration:.2f}s" if duration is not None else "unknown"
        logger.info(
            "[%s] HTTP response headers received: %s %s status=%s elapsed=%s",
            label,
            response.request.method,
            response.request.url.path,
            response.status_code,
            elapsed,
        )
        # Spec 15.1: llm_requests_total/llm_request_duration_seconds cover
        # actual generation calls only, not the embeddings endpoint (spec's
        # metric list has no separate embeddings metric) — this client is
        # shared by both (see external_client below vs. backend/rag/embeddings.py).
        if label == "gemini-chat":
            metrics.llm_requests_total.labels(
                model=MODEL_NAME, status="success" if response.status_code < 400 else "error"
            ).inc()
            if duration is not None:
                metrics.llm_request_duration_seconds.observe(duration)

    return httpx.AsyncClient(
        timeout=timeout_seconds,
        event_hooks={"request": [_log_request], "response": [_log_response]},
    )


# Gemini has no native OpenAI platform key, so it's accessed through its
# OpenAI-compatible endpoint. An explicit timeout bounds how long a turn can
# hang if the network path to Gemini stalls (egress issue, black-holed
# connection) rather than failing fast with an HTTP error — the OpenAI SDK's
# default timeout is 10 minutes, far longer than a chat turn should ever
# wait, and a hang here produces no exception and nothing in the logs.
external_client = AsyncOpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    http_client=build_traced_http_client("gemini-chat", 30.0),
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


# ---------------------------------------------------------------------------
# Circuit breaker (spec 6.1.1)
# ---------------------------------------------------------------------------
#
# Sits above the per-call retry policy above: that policy handles a single
# turn's transient failures (a 503 mid-turn gets retried within the same
# turn), but says nothing about a *sustained* Gemini outage — every turn
# during it would still attempt the full retry sequence, each one taking as
# long as the retries do to fail, and hammering an already-struggling
# endpoint. The circuit breaker tracks failures across turns/process-wide and
# fails fast without calling the LLM at all once genuinely open, exactly the
# gap spec 6.1.1 describes.
CIRCUIT_FAILURE_THRESHOLD = 5
CIRCUIT_FAILURE_WINDOW_SECONDS = 60
CIRCUIT_OPEN_DURATION_SECONDS = 30

DEGRADED_MESSAGE = (
    "I'm experiencing temporary difficulties. Please try again in a few moments, "
    "or I can connect you with a support agent."
)

_failure_timestamps: list[float] = []
_circuit_opened_at: float | None = None


def record_llm_success() -> None:
    """Call after any turn that completed without an unhandled provider
    failure — clears the failure count, closing the circuit if it was
    half-open."""
    global _circuit_opened_at
    _failure_timestamps.clear()
    _circuit_opened_at = None


def record_llm_failure() -> None:
    """Call after a turn's LLM call failed even after the retry policy above
    exhausted its attempts. Opens the circuit once CIRCUIT_FAILURE_THRESHOLD
    failures land within CIRCUIT_FAILURE_WINDOW_SECONDS of each other."""
    global _circuit_opened_at
    now = time.monotonic()
    _failure_timestamps.append(now)
    while _failure_timestamps and now - _failure_timestamps[0] > CIRCUIT_FAILURE_WINDOW_SECONDS:
        _failure_timestamps.pop(0)
    if len(_failure_timestamps) >= CIRCUIT_FAILURE_THRESHOLD:
        _circuit_opened_at = now
        logger.warning(
            "Circuit breaker OPEN: %d LLM failures within %ds", len(_failure_timestamps), CIRCUIT_FAILURE_WINDOW_SECONDS
        )


def is_circuit_open() -> bool:
    """False during the "half-open" probe window (spec 6.1.1: one call is
    let through 30s after opening to test recovery) — the very next
    record_llm_success()/record_llm_failure() then closes or re-opens it."""
    if _circuit_opened_at is None:
        return False
    return time.monotonic() - _circuit_opened_at < CIRCUIT_OPEN_DURATION_SECONDS
