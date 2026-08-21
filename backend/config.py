from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded exclusively from environment variables / .env.

    Never hardcode secrets here — every field is populated from the environment.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM provider
    gemini_api_key: str = ""
    gemini_model_name: str = "gemini-flash-latest"
    gemini_embedding_model: str = "gemini-embedding-001"

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://support_user:support_pass@localhost:5432/support_agent"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # Escalation notifications
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    slack_webhook_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
