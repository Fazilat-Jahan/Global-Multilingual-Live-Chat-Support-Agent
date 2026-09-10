"""Unit tests for the spec 6.1.1 circuit breaker in backend.model_provider:
opens after 5 failures within 60s, half-open probe after 30s, closes again
on a success."""

from backend import model_provider


def _reset():
    model_provider._failure_timestamps.clear()
    model_provider._circuit_opened_at = None


def test_circuit_stays_closed_below_the_failure_threshold():
    _reset()
    for _ in range(model_provider.CIRCUIT_FAILURE_THRESHOLD - 1):
        model_provider.record_llm_failure()
    assert model_provider.is_circuit_open() is False


def test_circuit_opens_at_the_failure_threshold():
    _reset()
    for _ in range(model_provider.CIRCUIT_FAILURE_THRESHOLD):
        model_provider.record_llm_failure()
    assert model_provider.is_circuit_open() is True


def test_circuit_closes_again_on_success():
    _reset()
    for _ in range(model_provider.CIRCUIT_FAILURE_THRESHOLD):
        model_provider.record_llm_failure()
    assert model_provider.is_circuit_open() is True

    model_provider.record_llm_success()
    assert model_provider.is_circuit_open() is False


def test_old_failures_outside_the_window_do_not_count(monkeypatch):
    _reset()
    now = [1000.0]
    monkeypatch.setattr(model_provider.time, "monotonic", lambda: now[0])

    for _ in range(model_provider.CIRCUIT_FAILURE_THRESHOLD - 1):
        model_provider.record_llm_failure()

    # Jump well past the failure window before the final failure — the
    # earlier ones should have aged out, so this alone isn't enough to open.
    now[0] += model_provider.CIRCUIT_FAILURE_WINDOW_SECONDS + 1
    model_provider.record_llm_failure()

    assert model_provider.is_circuit_open() is False


def test_circuit_half_opens_after_the_open_duration(monkeypatch):
    _reset()
    now = [2000.0]
    monkeypatch.setattr(model_provider.time, "monotonic", lambda: now[0])

    for _ in range(model_provider.CIRCUIT_FAILURE_THRESHOLD):
        model_provider.record_llm_failure()
    assert model_provider.is_circuit_open() is True

    now[0] += model_provider.CIRCUIT_OPEN_DURATION_SECONDS + 1
    assert model_provider.is_circuit_open() is False
