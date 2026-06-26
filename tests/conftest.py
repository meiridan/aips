"""Shared pytest fixtures.

Phase 3 adds a real-Postgres fixture (`db_sessionmaker`) that builds an
isolated `maya_test` database from the SQLAlchemy models, recreated per test
for clean isolation. DB-backed tests are skipped automatically when Postgres
is not reachable (mirrors the integration-test skip pattern).
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from maya.db.models import Base

_DEV_URL = (
    os.environ.get("DATABASE_URL")
    or "postgresql+asyncpg://postgres:postgres@localhost:5432/maya"
)
_TEST_DBNAME = "maya_test"


def _swap_dbname(url: str, name: str) -> str:
    head, _, _old = url.rpartition("/")
    # strip any query string off the original dbname, then re-point
    return f"{head}/{name}"


_TEST_URL = _swap_dbname(_DEV_URL, _TEST_DBNAME)
_LIBPQ_DEV = _DEV_URL.replace("postgresql+asyncpg://", "postgresql://")
_LIBPQ_TEST = _TEST_URL.replace("postgresql+asyncpg://", "postgresql://")


def _db_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(_LIBPQ_DEV, connect_timeout=2):
            return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()
db_required = pytest.mark.skipif(not DB_AVAILABLE, reason="Postgres not reachable")


@pytest.fixture(scope="session")
def _ensure_test_db() -> None:
    """Create the maya_test database + pgvector extension once per session."""
    if not DB_AVAILABLE:
        return
    import psycopg

    with psycopg.connect(_LIBPQ_DEV, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (_TEST_DBNAME,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{_TEST_DBNAME}"')
    with psycopg.connect(_LIBPQ_TEST, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


@pytest_asyncio.fixture
async def db_sessionmaker(_ensure_test_db):
    """Async sessionmaker bound to a freshly-built maya_test schema.

    Tables are dropped + recreated around each test for isolation.
    """
    if not DB_AVAILABLE:
        pytest.skip("Postgres not reachable")
    engine = create_async_engine(_TEST_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield sm
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded_ids(db_sessionmaker):
    """Insert a user + companion, return (user_id, companion_id)."""
    from maya.db.models import Companion, User

    async with db_sessionmaker() as session:
        user = User(name="Tester")
        session.add(user)
        await session.flush()
        comp = Companion(user_id=user.id, name="Maya", template_id="flirt")
        session.add(comp)
        await session.commit()
        return user.id, comp.id
