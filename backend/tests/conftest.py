"""Core test fixtures: async DB, session rollback, FastAPI test client, auth."""

from typing import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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

# ---------------------------------------------------------------------------
# Test database URL – same postgres, different database name
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = settings.DATABASE_URL.rsplit("/", 1)[0] + "/investing_companion_test"


# ---------------------------------------------------------------------------
# Session-scoped: create engine + tables once per test run
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create async engine and tables; tear down after entire suite."""
    _engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


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
