"""Integration tests for the Phase 13 Alembic migration tooling (spec 6.2):
verifies the alembic config, directory structure, and live migration
commands against the dev Postgres instance.
"""

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "db" / "migrations"
VERSIONS_DIR = MIGRATIONS_DIR / "versions"
ENV_PY = MIGRATIONS_DIR / "env.py"
SCRIPT_MAKO = MIGRATIONS_DIR / "script.py.mako"

BASELINE_REVISION = "903a7a279ae3"


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    """Run an alembic command from the backend/ directory."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_alembic_ini_exists_and_is_parseable():
    assert ALEMBIC_INI.exists(), "backend/alembic.ini must exist"
    content = ALEMBIC_INI.read_text()
    assert "[alembic]" in content
    assert "script_location" in content


def test_migration_directory_structure():
    assert MIGRATIONS_DIR.is_dir(), "backend/db/migrations/ must be a directory"
    assert VERSIONS_DIR.is_dir(), "backend/db/migrations/versions/ must be a directory"
    assert ENV_PY.exists(), "backend/db/migrations/env.py must exist"
    assert SCRIPT_MAKO.exists(), "backend/db/migrations/script.py.mako must exist"
    # At least one migration file in versions/
    migration_files = list(VERSIONS_DIR.glob("*.py"))
    migration_files = [f for f in migration_files if f.name != "__init__.py"]
    assert len(migration_files) >= 1, "at least one migration script must exist"


def test_alembic_heads_reports_single_head():
    """A healthy Alembic tree has exactly one head (no branch conflicts)."""
    result = _alembic("heads")
    assert result.returncode == 0, f"alembic heads failed: {result.stderr}"
    heads = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    assert len(heads) == 1, f"expected exactly 1 head, got {len(heads)}: {heads}"
    assert BASELINE_REVISION in heads[0]


def test_alembic_current_shows_baseline():
    """The dev DB was stamped at the baseline revision."""
    result = _alembic("current")
    assert result.returncode == 0, f"alembic current failed: {result.stderr}"
    assert BASELINE_REVISION in result.stdout, (
        f"expected current revision to contain {BASELINE_REVISION}, got: {result.stdout}"
    )


def test_alembic_upgrade_head_is_idempotent():
    """Running upgrade head when already at head is a safe no-op."""
    result = _alembic("upgrade", "head")
    assert result.returncode == 0, f"alembic upgrade head failed: {result.stderr}"


def test_alembic_check_detects_no_pending_changes():
    """`alembic check` exits 0 when the DB matches the models (no autogenerate diff)."""
    result = _alembic("check")
    assert result.returncode == 0, f"alembic check detected pending changes: {result.stdout}\n{result.stderr}"


@pytest.mark.asyncio
async def test_env_py_imports_target_metadata():
    """The env.py imports Base.metadata from backend.db.models (autogenerate support)."""
    content = ENV_PY.read_text()
    assert "from backend.db.models import Base" in content
    assert "target_metadata = Base.metadata" in content
