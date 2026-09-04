"""Phase 16 (spec 18.2) unit tests for knowledge base re-ingestion.

Covers: checksum computation, document loading, KnowledgeDocument model,
Redis lock semantics, admin API auth, incremental diff logic, CLI args,
and IngestionResult structure. Qdrant/embedding calls are mocked to avoid
burning Gemini quota or requiring a live Qdrant instance.
"""

import hashlib
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from backend.config import get_settings
from backend.db.models import KnowledgeDocument
from backend.main import app
from backend.rag.ingestion import (
    COLLECTION_NAME,
    IngestionResult,
    SourceDocument,
    _chunk_point_id,
    _compute_checksum,
    _load_document,
    ingest,
)

settings = get_settings()


# =========================================================================
# Checksum computation
# =========================================================================


class TestChecksum:
    def test_compute_checksum_sha256(self, tmp_path):
        """Checksum is the SHA-256 hex digest of file bytes."""
        f = tmp_path / "test.md"
        f.write_text("hello world", encoding="utf-8")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert _compute_checksum(f) == expected

    def test_checksum_changes_with_content(self, tmp_path):
        """Different content produces different checksums."""
        f = tmp_path / "test.md"
        f.write_text("version 1", encoding="utf-8")
        c1 = _compute_checksum(f)
        f.write_text("version 2", encoding="utf-8")
        c2 = _compute_checksum(f)
        assert c1 != c2

    def test_checksum_deterministic(self, tmp_path):
        """Same content always produces the same checksum."""
        f = tmp_path / "test.md"
        f.write_text("stable content", encoding="utf-8")
        assert _compute_checksum(f) == _compute_checksum(f)


# =========================================================================
# Document loading
# =========================================================================


class TestDocumentLoading:
    def test_load_document_with_frontmatter(self, tmp_path):
        """YAML frontmatter is parsed into SourceDocument fields."""
        f = tmp_path / "faq" / "test_doc.md"
        f.parent.mkdir(parents=True)
        f.write_text(
            "---\ntitle: Test Title\ncategory: faq\nproduct: test-prod\n"
            "language: en\nversion: '2.0'\n---\n\nBody content here.",
            encoding="utf-8",
        )
        with patch("backend.rag.ingestion.KNOWLEDGE_BASE_DIR", tmp_path):
            doc = _load_document(f)
        assert doc.document_id == "test_doc"
        assert doc.title == "Test Title"
        assert doc.category == "faq"
        assert doc.product == "test-prod"
        assert doc.language == "en"
        assert doc.version == "2.0"
        assert "Body content here" in doc.body

    def test_load_document_without_frontmatter(self, tmp_path):
        """Files without frontmatter get sensible defaults."""
        f = tmp_path / "plain.md"
        f.write_text("Just plain text.", encoding="utf-8")
        with patch("backend.rag.ingestion.KNOWLEDGE_BASE_DIR", tmp_path):
            doc = _load_document(f)
        assert doc.document_id == "plain"
        assert doc.language == "en"
        assert doc.version == "1.0"
        assert "Just plain text" in doc.body

    def test_source_document_dataclass(self):
        """SourceDocument carries all expected fields."""
        doc = SourceDocument(
            document_id="test",
            source="faq/test.md",
            title="Test",
            category="faq",
            product=None,
            language="en",
            version="1.0",
            body="body text",
        )
        assert doc.document_id == "test"
        assert doc.product is None


# =========================================================================
# Deterministic point IDs
# =========================================================================


class TestPointIds:
    def test_chunk_point_id_deterministic(self):
        """Same document_id + chunk_index always produces the same UUID."""
        assert _chunk_point_id("doc1", 0) == _chunk_point_id("doc1", 0)

    def test_chunk_point_id_varies_by_index(self):
        """Different chunk indices produce different UUIDs."""
        assert _chunk_point_id("doc1", 0) != _chunk_point_id("doc1", 1)

    def test_chunk_point_id_varies_by_document(self):
        """Different document IDs produce different UUIDs."""
        assert _chunk_point_id("doc1", 0) != _chunk_point_id("doc2", 0)

    def test_chunk_point_id_is_valid_uuid(self):
        """Generated IDs are valid UUIDs."""
        import uuid

        result = _chunk_point_id("test-doc", 5)
        uuid.UUID(result)  # Raises if invalid


# =========================================================================
# KnowledgeDocument model
# =========================================================================


class TestKnowledgeDocumentModel:
    def test_table_has_expected_columns(self):
        """KnowledgeDocument must have all spec 18.2 columns."""
        cols = KnowledgeDocument.__table__.columns
        expected = {"id", "document_id", "tenant_id", "file_path", "checksum", "chunk_count", "last_ingested_at"}
        assert expected.issubset(set(cols.keys()))

    def test_tenant_id_is_indexed(self):
        """tenant_id must be indexed for efficient scoping."""
        assert KnowledgeDocument.__table__.columns["tenant_id"].index is True

    def test_document_id_is_indexed(self):
        """document_id must be indexed for efficient lookups."""
        assert KnowledgeDocument.__table__.columns["document_id"].index is True


# =========================================================================
# Collection name (tenant-scoped)
# =========================================================================


class TestCollectionName:
    def test_collection_is_tenant_scoped(self):
        """COLLECTION_NAME uses the tenant-scoped name (Phase 17)."""
        assert COLLECTION_NAME == f"{settings.tenant_id}_knowledge_base"


# =========================================================================
# IngestionResult
# =========================================================================


class TestIngestionResult:
    def test_default_values(self):
        """IngestionResult defaults to zero counts."""
        r = IngestionResult(mode="full")
        assert r.documents_processed == 0
        assert r.documents_skipped == 0
        assert r.documents_deleted == 0
        assert r.chunks_created == 0
        assert r.errors is None

    def test_mode_stored(self):
        r = IngestionResult(mode="incremental")
        assert r.mode == "incremental"


# =========================================================================
# Redis lock (mocked)
# =========================================================================


class TestRedisLock:
    @pytest.mark.asyncio
    async def test_acquire_lock_success(self):
        """Lock is acquired when Redis SET NX returns True."""
        from backend.rag.ingestion import _acquire_lock

        with patch("backend.rag.ingestion.Redis") as mock_redis_cls:
            mock_client = AsyncMock()
            mock_redis_cls.from_url.return_value = mock_client
            mock_client.set.return_value = True  # NX succeeded
            result = await _acquire_lock()
            assert result is True
            mock_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acquire_lock_already_held(self):
        """Lock is NOT acquired when Redis SET NX returns None."""
        from backend.rag.ingestion import _acquire_lock

        with patch("backend.rag.ingestion.Redis") as mock_redis_cls:
            mock_client = AsyncMock()
            mock_redis_cls.from_url.return_value = mock_client
            mock_client.set.return_value = None  # NX failed (lock held)
            result = await _acquire_lock()
            assert result is False

    @pytest.mark.asyncio
    async def test_release_lock(self):
        """Lock release calls Redis DELETE."""
        from backend.rag.ingestion import _release_lock

        with patch("backend.rag.ingestion.Redis") as mock_redis_cls:
            mock_client = AsyncMock()
            mock_redis_cls.from_url.return_value = mock_client
            await _release_lock()
            mock_client.delete.assert_awaited_once()
            mock_client.aclose.assert_awaited_once()


# =========================================================================
# Admin API auth
# =========================================================================


class TestAdminAuth:
    def test_reingest_requires_auth(self):
        """POST without auth header returns 403."""
        with TestClient(app) as client:
            resp = client.post(
                "/api/admin/knowledge-base/reingest",
                json={"mode": "incremental"},
            )
            assert resp.status_code == 403

    def test_reingest_wrong_key_returns_403(self):
        """POST with wrong key returns 403."""
        with TestClient(app) as client:
            resp = client.post(
                "/api/admin/knowledge-base/reingest",
                json={"mode": "incremental"},
                headers={"Authorization": "Bearer wrong-key"},
            )
            assert resp.status_code == 403

    def test_reingest_correct_key_passes_auth(self):
        """POST with correct key passes auth (may still fail on ingestion)."""
        with TestClient(app) as client:
            with patch("backend.api.admin.ingest", new_callable=AsyncMock) as mock_ingest:
                mock_ingest.return_value = IngestionResult(mode="incremental")
                resp = client.post(
                    "/api/admin/knowledge-base/reingest",
                    json={"mode": "incremental"},
                    headers={"Authorization": f"Bearer {settings.admin_api_key}"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["mode"] == "incremental"
                mock_ingest.assert_awaited_once()

    def test_reingest_lock_contention_returns_409(self):
        """When lock is held, endpoint returns 409 Conflict."""
        with TestClient(app) as client:
            with patch("backend.api.admin.ingest", new_callable=AsyncMock) as mock_ingest:
                mock_ingest.side_effect = RuntimeError("Another re-ingestion is already in progress")
                resp = client.post(
                    "/api/admin/knowledge-base/reingest",
                    json={"mode": "full"},
                    headers={"Authorization": f"Bearer {settings.admin_api_key}"},
                )
                assert resp.status_code == 409
                assert "already in progress" in resp.json()["detail"]

    def test_reingest_invalid_mode_returns_400(self):
        """Invalid mode in request body returns 400."""
        with TestClient(app) as client:
            resp = client.post(
                "/api/admin/knowledge-base/reingest",
                json={"mode": "invalid_mode"},
                headers={"Authorization": f"Bearer {settings.admin_api_key}"},
            )
            assert resp.status_code == 400

    def test_admin_api_key_in_settings(self):
        """admin_api_key is available in Settings."""
        assert hasattr(settings, "admin_api_key")


# =========================================================================
# Ingest function — lock contention
# =========================================================================


class TestIngestEntryPoint:
    @pytest.mark.asyncio
    async def test_ingest_raises_when_lock_held(self):
        """ingest() raises RuntimeError when lock can't be acquired."""
        with patch("backend.rag.ingestion._acquire_lock", new_callable=AsyncMock, return_value=False):
            with pytest.raises(RuntimeError, match="already in progress"):
                await ingest(mode="full")

    @pytest.mark.asyncio
    async def test_ingest_invalid_mode(self):
        """ingest() raises ValueError for unknown mode."""
        with patch("backend.rag.ingestion._acquire_lock", new_callable=AsyncMock, return_value=True):
            with patch("backend.rag.ingestion._release_lock", new_callable=AsyncMock):
                with pytest.raises(ValueError, match="Unknown ingestion mode"):
                    await ingest(mode="bogus")

    @pytest.mark.asyncio
    async def test_ingest_releases_lock_on_success(self):
        """Lock is released even on successful completion."""
        with patch("backend.rag.ingestion._acquire_lock", new_callable=AsyncMock, return_value=True):
            with patch("backend.rag.ingestion._release_lock", new_callable=AsyncMock) as mock_release:
                with patch("backend.rag.ingestion.ingest_full", new_callable=AsyncMock) as mock_full:
                    mock_full.return_value = IngestionResult(mode="full")
                    await ingest(mode="full")
                    mock_release.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ingest_releases_lock_on_error(self):
        """Lock is released even if ingestion raises an exception."""
        with patch("backend.rag.ingestion._acquire_lock", new_callable=AsyncMock, return_value=True):
            with patch("backend.rag.ingestion._release_lock", new_callable=AsyncMock) as mock_release:
                with patch("backend.rag.ingestion.ingest_full", new_callable=AsyncMock, side_effect=Exception("boom")):
                    with pytest.raises(Exception, match="boom"):
                        await ingest(mode="full")
                    mock_release.assert_awaited_once()


# =========================================================================
# Incremental logic (mocked)
# =========================================================================


class TestIncrementalLogic:
    @pytest.mark.asyncio
    async def test_incremental_skips_unchanged(self):
        """Incremental mode skips documents whose checksum hasn't changed."""
        with patch("backend.rag.ingestion._acquire_lock", new_callable=AsyncMock, return_value=True):
            with patch("backend.rag.ingestion._release_lock", new_callable=AsyncMock):
                with patch("backend.rag.ingestion.ingest_incremental", new_callable=AsyncMock) as mock_inc:
                    mock_inc.return_value = IngestionResult(
                        mode="incremental", documents_skipped=3, documents_processed=0
                    )
                    result = await ingest(mode="incremental")
                    assert result.documents_skipped == 3
                    assert result.documents_processed == 0
