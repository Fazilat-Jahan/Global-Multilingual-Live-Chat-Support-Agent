"""Spec 6.1.2 / 15.1: application-level structured logging with trace
correlation — the replacement for OpenAI SDK tracing, which is disabled in
backend/model_provider.py because Gemini is accessed through its Chat
Completions compatibility layer, not an OpenAI platform key.

Wraps the existing stdlib `logging` module rather than requiring every
call site across backend/ to switch to structlog's own API: every
`logger.info(...)` / `logger.warning(...)` / `logger.exception(...)` call
already in this codebase is preserved verbatim. This module only changes
how those records are rendered (JSON in production, human-readable console
in development) and enriches every one of them with whatever's currently
bound via bind_trace_context() — trace_id, session_id, and anything else —
without threading those values through every function signature.
"""

import logging
import sys

import structlog

from backend.config import get_settings

settings = get_settings()

_SHARED_PROCESSORS = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
]


def configure_logging() -> None:
    """Call once, at process startup (backend/main.py) — replaces the
    logging.basicConfig() call it used to make, at the same point in
    import order (before any other module's logging.getLogger(__name__)
    calls run) so every subsequent logger picks this up."""
    renderer = (
        structlog.processors.JSONRenderer() if settings.app_env == "production" else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*_SHARED_PROCESSORS, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))


def bind_trace_context(*, trace_id: str, session_id: str | None = None, **extra: str) -> None:
    """Binds trace_id/session_id (and anything else) into structlog's
    contextvars so every log call for the remainder of this async task —
    across service methods, agent invocations, tool calls, guardrail
    evaluations, and DB queries — automatically includes them. Call once
    per inbound WebSocket message or HTTP request (backend/websocket/handler.py,
    backend/middleware/*)."""
    structlog.contextvars.bind_contextvars(trace_id=trace_id, session_id=session_id, **extra)


def clear_trace_context() -> None:
    structlog.contextvars.clear_contextvars()
