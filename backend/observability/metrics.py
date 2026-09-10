"""Spec 15.1: Prometheus-compatible metrics, exposed at GET /metrics
(backend/api/metrics.py). Every metric name/type/label set here matches
spec 15.1's table exactly.
"""

from prometheus_client import Counter, Gauge, Histogram

conversations_total = Counter("conversations_total", "Total conversations, by status", ["status"])
message_latency_seconds = Histogram(
    "message_latency_seconds", "Time to process one message turn, by final agent", ["agent"]
)
llm_requests_total = Counter("llm_requests_total", "Total LLM API requests, by model and outcome", ["model", "status"])
llm_request_duration_seconds = Histogram("llm_request_duration_seconds", "LLM API request duration")
guardrail_triggers_total = Counter(
    "guardrail_triggers_total", "Guardrail tripwire activations, by guardrail type and rule", ["type", "rule"]
)
rag_retrieval_score = Histogram("rag_retrieval_score", "Top cosine-similarity score of RAG retrieval results")
escalations_total = Counter("escalations_total", "Total escalations to the human queue, by reason", ["reason"])
websocket_connections_active = Gauge("websocket_connections_active", "Currently open WebSocket connections")
rate_limit_hits_total = Counter("rate_limit_hits_total", "Rate limit rejections, by scope", ["scope"])
