"""Phase 17 (spec 20.3) unit tests for tenant scoping completion.

Verifies that every data store in the system is scoped by tenant_id:
- PostgreSQL: Message model has tenant_id field; repository sets it.
- Redis: session, rate-limit, and verification keys prefixed with {tenant_id}:
- Qdrant: collection name is {tenant_id}_knowledge_base (not bare "knowledge_base").
"""

from backend.config import get_settings
from backend.db.models import Message
from backend.rag.ingestion import COLLECTION_NAME
from backend.services import rate_limit_service, session_service, verification_service

settings = get_settings()


# =========================================================================
# PostgreSQL: Message model
# =========================================================================


class TestMessageTenantId:
    def test_message_model_has_tenant_id_field(self):
        """Message must carry a tenant_id for row-level isolation (spec 20.3)."""
        assert "tenant_id" in Message.__table__.columns

    def test_message_tenant_id_default(self):
        """Default tenant_id is 'default' (matches settings.tenant_id for the dev env)."""
        col = Message.__table__.columns["tenant_id"]
        assert col.default is not None
        assert col.default.arg == "default"

    def test_message_tenant_id_is_indexed(self):
        """tenant_id on messages must be indexed for efficient scoping queries."""
        col = Message.__table__.columns["tenant_id"]
        assert col.index is True

    def test_conversation_and_ticket_also_have_tenant_id(self):
        """Sanity check: Conversation and Ticket already had tenant_id (Phase 8)."""
        from backend.db.models import Conversation, Ticket

        assert "tenant_id" in Conversation.__table__.columns
        assert "tenant_id" in Ticket.__table__.columns


# =========================================================================
# Redis: key prefixes
# =========================================================================


class TestRedisTenantPrefix:
    def test_session_service_key_prefix(self):
        """Session cache keys must start with {tenant_id}:."""
        assert session_service._SESSION_KEY_PREFIX.startswith(f"{settings.tenant_id}:")

    def test_rate_limit_key_prefix(self):
        """Rate-limit counter keys must start with {tenant_id}:."""
        assert rate_limit_service._KEY_PREFIX.startswith(f"{settings.tenant_id}:")

    def test_verification_verified_key_prefix(self):
        """Verified-customer-IDs SET key must start with {tenant_id}:."""
        assert verification_service._VERIFIED_KEY_PREFIX.startswith(f"{settings.tenant_id}:")

    def test_verification_attempts_key_prefix(self):
        """Verification attempt counter key must start with {tenant_id}:."""
        assert verification_service._ATTEMPTS_KEY_PREFIX.startswith(f"{settings.tenant_id}:")

    def test_verification_failures_key_prefix(self):
        """Verification failure counter key must start with {tenant_id}:."""
        assert verification_service._FAILURES_KEY_PREFIX.startswith(f"{settings.tenant_id}:")

    def test_session_key_format(self):
        """Full session key format: {tenant_id}:session:conversation_id:{session_id}."""
        expected = f"{settings.tenant_id}:session:conversation_id:"
        assert session_service._SESSION_KEY_PREFIX == expected

    def test_rate_limit_key_format(self):
        """Full rate-limit key format: {tenant_id}:ratelimit:{scope}:{id}."""
        expected = f"{settings.tenant_id}:ratelimit:"
        assert rate_limit_service._KEY_PREFIX == expected


# =========================================================================
# Qdrant: collection naming
# =========================================================================


class TestQdrantCollectionName:
    def test_collection_name_is_tenant_scoped(self):
        """Collection name must be {tenant_id}_knowledge_base (spec 20.3)."""
        assert COLLECTION_NAME == f"{settings.tenant_id}_knowledge_base"

    def test_collection_name_is_not_bare(self):
        """The bare 'knowledge_base' name (Phase 8) is no longer used."""
        assert COLLECTION_NAME != "knowledge_base"

    def test_settings_qdrant_collection_name_property(self):
        """Settings.qdrant_collection_name returns the same value as the
        ingestion module's COLLECTION_NAME."""
        assert settings.qdrant_collection_name == COLLECTION_NAME


# =========================================================================
# Settings helpers
# =========================================================================


class TestSettingsTenantHelpers:
    def test_tenant_key_prefix(self):
        assert settings.tenant_key_prefix == f"{settings.tenant_id}:"

    def test_qdrant_collection_name_property(self):
        assert settings.qdrant_collection_name == f"{settings.tenant_id}_knowledge_base"
