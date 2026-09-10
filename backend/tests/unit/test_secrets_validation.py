"""Unit tests for the spec 20.2 startup secrets validation: refuses to start
in production with a missing GEMINI_API_KEY or a missing/too-short
SESSION_SECRET; is a no-op outside production (dev/test must never be
locked out by this).
"""

import pytest

from backend.config import SecretsValidationError, Settings, validate_required_secrets


def _settings(**overrides) -> Settings:
    base = {
        "app_env": "production",
        "gemini_api_key": "real-key",
        "session_secret": "x" * 32,
    }
    base.update(overrides)
    return Settings(**base)


def test_passes_with_all_required_secrets_present_in_production():
    validate_required_secrets(_settings())  # must not raise


def test_raises_in_production_when_gemini_api_key_missing():
    with pytest.raises(SecretsValidationError, match="GEMINI_API_KEY"):
        validate_required_secrets(_settings(gemini_api_key=""))


def test_raises_in_production_when_session_secret_missing():
    with pytest.raises(SecretsValidationError, match="SESSION_SECRET"):
        validate_required_secrets(_settings(session_secret=""))


def test_raises_in_production_when_session_secret_too_short():
    with pytest.raises(SecretsValidationError, match="at least 32 characters"):
        validate_required_secrets(_settings(session_secret="short"))


def test_is_a_noop_outside_production_even_with_everything_missing():
    settings = _settings(app_env="development", gemini_api_key="", session_secret="")
    validate_required_secrets(settings)  # must not raise
