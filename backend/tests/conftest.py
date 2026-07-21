"""Core test fixtures: async DB, session rollback, FastAPI test client, auth."""

import sys
from typing import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine.url import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base

# Import all models so Base.metadata.create_all picks them up
from app.db.models import *  # noqa: F401, F403
from app.db.session import get_db
from app.main import app
from app.services.auth import AuthService
from tests.db_naming import resolve_test_database_url

# ---------------------------------------------------------------------------
# Test database URL — worktree-safe (see tests/db_naming.py).
#
# TEST_DATABASE_URL overrides everything and is caller-managed (e.g. CI's
# pre-provisioned service container — .github/workflows/ci.yml pins it to
# the DB the postgres service already created). Absent an override, a name
# derived from THIS checkout's own path is used, and this suite owns that
# database's create/drop lifecycle end to end — a plain single dev checkout
# needs zero setup either way.
# ---------------------------------------------------------------------------
TEST_DATABASE_URL, _TEST_DB_IS_OVERRIDE = resolve_test_database_url(
    __file__, settings.DATABASE_URL
)
print(
    f"[tests/conftest] test database: "
    f"{TEST_DATABASE_URL.render_as_string(hide_password=True)} "
    f"(override={_TEST_DB_IS_OVERRIDE})",
    file=sys.stderr,
)


async def _create_test_database_if_missing(url: URL) -> None:
    """CREATE DATABASE for a derived test DB if it doesn't exist yet.

    Only called for derived (non-override) URLs — an overridden database's
    lifecycle belongs to the caller. Connects to the `postgres` maintenance
    database with the same credentials as `url`.
    """
    db_name = url.database
    maint_engine = create_async_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        async with maint_engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            )
            if exists:
                return
            try:
                # db_name is our own derived name — validated ASCII
                # alnum/underscore-only by db_naming.validate_test_db_name,
                # so this is safe to splice into DDL (CREATE DATABASE
                # doesn't accept the target as a bind parameter).
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
            except DBAPIError as exc:
                sqlstate = getattr(exc.orig, "sqlstate", None)
                if sqlstate == "42P04":
                    # duplicate_database: another process created it first
                    # between our existence check and CREATE — fine.
                    return
                if sqlstate == "42501":
                    raise RuntimeError(
                        f"Cannot create test database {db_name!r}: the "
                        "database role lacks CREATEDB privilege. Grant "
                        f"CREATEDB, create {db_name!r} manually, or set "
                        "TEST_DATABASE_URL to point at an existing database."
                    ) from exc
                raise
    finally:
        await maint_engine.dispose()


async def _drop_test_database(url: URL) -> None:
    """DROP DATABASE for a derived test DB at session end.

    Only called for derived (non-override) URLs. WITH (FORCE) (PG13+)
    disconnects any straggler session so teardown never leaves an orphaned
    derived database behind even if a connection didn't fully release.
    """
    db_name = url.database
    maint_engine = create_async_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        async with maint_engine.connect() as conn:
            await conn.execute(
                text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
            )
    finally:
        await maint_engine.dispose()


# ---------------------------------------------------------------------------
# Session-scoped: create engine + tables once per test run
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create async engine and tables; tear down after entire suite.

    For a derived (non-override) database this also owns the database's own
    lifecycle: create it if missing before first connect, drop it after the
    engine disposes. A TEST_DATABASE_URL override skips both — that
    database is caller-managed (e.g. CI's service container).
    """
    if not _TEST_DB_IS_OVERRIDE:
        await _create_test_database_if_missing(TEST_DATABASE_URL)
    _engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()
    if not _TEST_DB_IS_OVERRIDE:
        await _drop_test_database(TEST_DATABASE_URL)


# ---------------------------------------------------------------------------
# Function-scoped: one session per test, using savepoint for rollback
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session wrapped in a savepoint.

    The outer transaction is never committed, so all writes are rolled back
    after each test — even when service code calls session.commit().
    """
    async with engine.connect() as conn:
        txn = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)

        # Use begin_nested() so that session.commit() inside services
        # only commits the savepoint, not the outer transaction.
        await conn.begin_nested()

        # Re-open a nested savepoint every time the previous one ends
        # (i.e. when service code calls commit or rollback).
        from sqlalchemy import event

        @event.listens_for(session.sync_session, "after_transaction_end")
        def _restart_savepoint(sess, transaction):
            if conn.closed:
                return
            if not conn.in_nested_transaction():
                conn.sync_connection.begin_nested()

        try:
            yield session
        finally:
            await session.close()
            await txn.rollback()


# ---------------------------------------------------------------------------
# FastAPI test client with DB override
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client wired to the test database session."""

    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def test_user(db: AsyncSession):
    """Create and return a test user."""
    from tests.factories import create_test_user

    return await create_test_user(db)


@pytest_asyncio.fixture
async def auth_headers(db: AsyncSession, test_user) -> dict:
    """Return Authorization headers for the test user."""
    auth_service = AuthService(db)
    token, _ = auth_service._create_access_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def authed_client(
    client: AsyncClient, auth_headers: dict
) -> AsyncClient:
    """Client with auth headers pre-set."""
    client.headers.update(auth_headers)
    return client
