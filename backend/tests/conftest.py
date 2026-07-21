"""Core test fixtures: async DB, session rollback, FastAPI test client, auth."""

import hashlib
import sys
from typing import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine.url import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
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


def _advisory_lock_key(db_name: str) -> int:
    """A stable signed-bigint key for pg_advisory_lock, derived from db_name.

    Two suites started from the SAME checkout derive the exact same db_name
    (see tests/db_naming.py). Keying the lock off the name (rather than e.g.
    a random value) means both suites compute the identical key independently
    — no shared state beyond Postgres itself is needed.
    """
    digest = hashlib.sha256(db_name.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def _acquire_checkout_lock(url: URL) -> tuple[AsyncEngine, AsyncConnection]:
    """Take a session-level Postgres advisory lock for this checkout's db name.

    Fixes codex finding 2: two suites run from ONE checkout derive the SAME
    database name. Without serialization, the duplicate-CREATE-DATABASE
    handling in _create_test_database_if_missing lets both proceed, and the
    first one's teardown (DROP DATABASE ... WITH (FORCE)) then kills the
    second one mid-run.

    Chosen behavior: FAIL FAST (pg_try_advisory_lock, non-blocking) rather
    than block-and-wait — a hung/crashed first run would otherwise wedge the
    second run indefinitely with no feedback. The lock is taken on a
    dedicated maintenance connection that this function returns un-closed;
    the caller must keep it open for the lifetime of the derived database
    (create through drop) and release it via _release_checkout_lock.
    """
    db_name = url.database
    key = _advisory_lock_key(db_name)
    lock_engine = create_async_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    conn = lock_engine.connect()
    try:
        await conn.start()
        acquired = await conn.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
        )
        if not acquired:
            raise RuntimeError(
                f"Another suite is already running from this checkout "
                f"(test database {db_name!r} is advisory-locked by another "
                "session). Wait for it to finish, or set TEST_DATABASE_URL "
                "to point this run at an independent database."
            )
    except Exception:
        await conn.close()
        await lock_engine.dispose()
        raise
    return lock_engine, conn


async def _release_checkout_lock(
    lock_engine: AsyncEngine, conn: AsyncConnection, db_name: str
) -> None:
    """Release the advisory lock taken by _acquire_checkout_lock and close up.

    Best-effort: pg_advisory_unlock failing (or being skipped because the
    connection is already dead) is not fatal — a session-level advisory lock
    is automatically released by Postgres when the holding connection closes
    or the backend terminates, so closing/disposing below is what actually
    guarantees release.
    """
    key = _advisory_lock_key(db_name)
    try:
        await conn.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    except Exception as exc:
        print(
            f"[tests/conftest] note: pg_advisory_unlock for {db_name!r} "
            f"raised {exc!r}; closing the connection releases it anyway.",
            file=sys.stderr,
        )
    finally:
        await conn.close()
        await lock_engine.dispose()


async def _create_test_database_if_missing(conn: AsyncConnection, db_name: str) -> None:
    """CREATE DATABASE for a derived test DB if it doesn't exist yet.

    Only called for derived (non-override) URLs — an overridden database's
    lifecycle belongs to the caller. `conn` is the already-open, AUTOCOMMIT
    maintenance connection returned by _acquire_checkout_lock (connected to
    the `postgres` maintenance database with the same credentials as the
    target URL) — reused rather than opened fresh so the advisory lock held
    on it stays in effect across create.
    """
    exists = await conn.scalar(
        text("SELECT 1 FROM pg_database WHERE datname = :name"),
        {"name": db_name},
    )
    if exists:
        return
    try:
        # db_name is our own derived name — validated ASCII
        # alnum/underscore-only by db_naming.validate_test_db_name, so this
        # is safe to splice into DDL (CREATE DATABASE doesn't accept the
        # target as a bind parameter).
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate == "42P04":
            # duplicate_database: another process created it first between
            # our existence check and CREATE — fine. (In practice the
            # checkout-level advisory lock above already prevents this for
            # same-checkout runs; this remains a safety net for anything
            # else that might race, e.g. a manually-created database.)
            return
        if sqlstate == "42501":
            raise RuntimeError(
                f"Cannot create test database {db_name!r}: the "
                "database role lacks CREATEDB privilege. Grant "
                f"CREATEDB, create {db_name!r} manually, or set "
                "TEST_DATABASE_URL to point at an existing database."
            ) from exc
        raise


async def _drop_test_database(conn: AsyncConnection, db_name: str) -> None:
    """DROP DATABASE for a derived test DB at session end.

    Only called for derived (non-override) URLs, and only while still
    holding this checkout's advisory lock (see _acquire_checkout_lock) — so
    a concurrent run from a DIFFERENT checkout, which derives a different
    name and therefore never contends for this lock, is never at risk from
    this DROP. WITH (FORCE) (PG13+) disconnects any straggler session so
    teardown never leaves an orphaned derived database behind even if a
    connection didn't fully release.
    """
    await conn.execute(
        text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
    )


# ---------------------------------------------------------------------------
# Session-scoped: create engine + tables once per test run
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create async engine and tables; tear down after entire suite.

    For a derived (non-override) database this also owns the database's own
    lifecycle: a session-level advisory lock serializes concurrent
    same-checkout runs (codex finding 2), the database is created if missing
    before first connect, and dropped after the engine disposes. A
    TEST_DATABASE_URL override skips all of the above — that database is
    caller-managed (e.g. CI's service container).

    Every step past lock acquisition is wrapped in nested try/finally so
    engine disposal and the derived-database drop are attempted on EVERY
    exit path (codex finding 3) — including a failed create_all()/
    drop_all() — since an orphaned derived database is worse than a noisy
    teardown warning. Lock acquisition itself is deliberately NOT inside
    that try/finally: if we never acquired the lock (e.g. another suite
    already holds it), we don't own this database and must not touch it.
    """
    lock_engine: AsyncEngine | None = None
    lock_conn: AsyncConnection | None = None
    _engine: AsyncEngine | None = None
    db_name = TEST_DATABASE_URL.database

    try:
        if not _TEST_DB_IS_OVERRIDE:
            lock_engine, lock_conn = await _acquire_checkout_lock(TEST_DATABASE_URL)
            await _create_test_database_if_missing(lock_conn, db_name)

        try:
            _engine = create_async_engine(TEST_DATABASE_URL, echo=False)
            async with _engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            yield _engine
        finally:
            if _engine is not None:
                try:
                    async with _engine.begin() as conn:
                        await conn.run_sync(Base.metadata.drop_all)
                except Exception as exc:
                    print(
                        f"[tests/conftest] WARNING: drop_all() failed for "
                        f"database {db_name!r}: {exc!r}. Tables may be left "
                        "behind in it, but the database itself is still "
                        "dropped below (derived databases are disposable).",
                        file=sys.stderr,
                    )
                finally:
                    await _engine.dispose()
    finally:
        if lock_conn is not None:
            assert lock_engine is not None  # always set together
            try:
                await _drop_test_database(lock_conn, db_name)
            except Exception as exc:
                print(
                    f"[tests/conftest] WARNING: failed to drop test "
                    f"database {db_name!r}: {exc!r}. It was left behind and "
                    "needs manual cleanup: "
                    f'DROP DATABASE "{db_name}" WITH (FORCE);',
                    file=sys.stderr,
                )
            finally:
                await _release_checkout_lock(lock_engine, lock_conn, db_name)


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
