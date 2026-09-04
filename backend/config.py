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

    # Rate limiting (Redis-backed fixed window; Phase 8)
    rate_limit_per_session_per_minute: int = 20
    rate_limit_per_ip_per_minute: int = 60

    # Light tenant isolation (Phase 8) — a single-value discriminator tagged
    # onto Qdrant points and DB rows, so a shared DB/Qdrant instance later
    # serving multiple clients can't cross-contaminate their data. Not a
    # full tenant-management system (out of scope for this MVP).
    tenant_id: str = "default"

    # Admin API key (Phase 16, spec 18.2) — protects the re-ingestion
    # endpoint. If empty, admin endpoints return 403. Set via env var in
    # production; the dev default allows local testing with any value.
    admin_api_key: str = ""

    # CORS / origin allowlist (spec 12.3) — comma-separated origins (scheme +
    # host + port, no trailing slash) allowed to call the API directly and to
    # open WebSocket upgrades. The embedded widget talks to this backend from
    # the widget host's own origin inside its iframe; anything else must be
    # explicitly listed. Default matches the local dev frontend; production
    # must set this to the client website domain(s) plus the widget host.
    allowed_origins: str = "http://localhost:3000"

    @property
    def allowed_origin_list(self) -> list[str]:
        """ALLOWED_ORIGINS parsed into a clean list (spec 12.3)."""
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def qdrant_collection_name(self) -> str:
        """Phase 17 (spec 20.3): per-tenant Qdrant collection name."""
        return f"{self.tenant_id}_knowledge_base"

    @property
    def tenant_key_prefix(self) -> str:
        """Phase 17 (spec 20.3): tenant-scoped prefix for all Redis keys."""
        return f"{self.tenant_id}:"


@lru_cache
def get_settings() -> Settings:
    return Settings()
