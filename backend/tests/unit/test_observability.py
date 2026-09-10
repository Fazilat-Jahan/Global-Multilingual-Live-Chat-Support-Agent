"""Unit tests for the spec 15/15.1 observability additions: the Prometheus
metrics registry exposes exactly the metrics spec 15.1's table lists, and
trace-context binding/clearing round-trips through structlog's contextvars.
"""

import structlog
from prometheus_client import generate_latest

from backend.observability import metrics
from backend.observability.logging_config import bind_trace_context, clear_trace_context


def test_all_spec_15_1_metrics_are_registered():
    # A Counter/Histogram *with labels* only appears in the exposition
    # output once some label combination has actually been observed — touch
    # each one first so this test is self-contained regardless of whether
    # test_metrics_are_actually_incrementable happened to run first in this
    # process (metrics are process-global singletons, not reset per test).
    metrics.conversations_total.labels(status="ACTIVE")
    metrics.message_latency_seconds.labels(agent="Triage Agent")
    metrics.llm_requests_total.labels(model="test-model", status="success")
    metrics.guardrail_triggers_total.labels(type="input", rule="test")
    metrics.escalations_total.labels(reason="test")
    metrics.rate_limit_hits_total.labels(scope="session")

    # generate_latest() renders the same exposition format a Prometheus
    # scrape of GET /metrics would see — Counter's exposed name always ends
    # in "_total" regardless of how prometheus_client stores it internally
    # (its `.name` attribute strips that suffix), so this checks the name
    # that actually matters rather than an internal implementation detail.
    exposed = generate_latest().decode()
    for expected_name in (
        "conversations_total",
        "message_latency_seconds",
        "llm_requests_total",
        "llm_request_duration_seconds",
        "guardrail_triggers_total",
        "rag_retrieval_score",
        "escalations_total",
        "websocket_connections_active",
        "rate_limit_hits_total",
    ):
        assert expected_name in exposed, f"{expected_name!r} not found in /metrics output"


def test_metrics_are_actually_incrementable():
    metrics.conversations_total.labels(status="ACTIVE").inc()
    metrics.guardrail_triggers_total.labels(type="input", rule="prompt_injection").inc()
    metrics.escalations_total.labels(reason="agent_handoff").inc()
    metrics.websocket_connections_active.inc()
    metrics.websocket_connections_active.dec()
    metrics.rate_limit_hits_total.labels(scope="session").inc()
    metrics.message_latency_seconds.labels(agent="RAG Agent").observe(1.23)
    metrics.rag_retrieval_score.observe(0.81)
    metrics.llm_requests_total.labels(model="gemini-flash-latest", status="success").inc()
    metrics.llm_request_duration_seconds.observe(0.5)


def test_bind_and_clear_trace_context_round_trips():
    clear_trace_context()
    assert structlog.contextvars.get_contextvars().get("trace_id") is None

    bind_trace_context(trace_id="trace-123", session_id="session-456")
    bound = structlog.contextvars.get_contextvars()
    assert bound["trace_id"] == "trace-123"
    assert bound["session_id"] == "session-456"

    clear_trace_context()
    assert structlog.contextvars.get_contextvars().get("trace_id") is None
