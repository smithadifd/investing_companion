"""Core test fixtures: async DB, session rollback, FastAPI test client, auth."""

import uuid
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# Session-scoped: create / drop all tables once per test run
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    """Create all tables before the test suite, drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Function-scoped: one session per test, rolled back for isolation
# ---------------------------------------------------------------------------
@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional database session that rolls back after each test."""
    async with engine.connect() as conn:
        txn = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await txn.rollback()


# ---------------------------------------------------------------------------
# FastAPI test client with DB override
# ---------------------------------------------------------------------------
@pytest.fixture
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
@pytest.fixture
async def test_user(db: AsyncSession):
    """Create and return a test user."""
    from tests.factories import create_test_user

    return await create_test_user(db)


@pytest.fixture
async def auth_headers(db: AsyncSession, test_user) -> dict:
    """Return Authorization headers for the test user."""
    auth_service = AuthService(db)
    token, _ = auth_service._create_access_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def authed_client(
    client: AsyncClient, auth_headers: dict
) -> AsyncClient:
    """Client with auth headers pre-set."""
    client.headers.update(auth_headers)
    return client
