"""Tests for the broker import trigger
(POST /api/v1/accounts/{account_id}/import).

This endpoint is the arm that was missing: before it, nothing in the running
application ever called ``schwab_ingestion.pull_positions`` /
``pull_transactions``, so a deployed reconciliation view could never leave its
``never_imported`` state.

Covers the auth/ownership/demo gates, the link gate, error mapping, the
positions/transactions/both selection, and - the load-bearing part - CROSS-USER
ISOLATION: that a pull is only ever issued for the AUTHENTICATED user with that
user's OWN linked hash, and that another user's account can neither be imported
into nor even be proven to exist.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account_link import AccountLink, AccountLinkStatus
from app.db.models.broker_import import (
    BrokerImportRun,
    ImportKind,
    ImportStatus,
)
from app.services import schwab_ingestion
from app.services.auth import AuthService
from app.services.data_providers.schwab import SchwabAPIError, SchwabAuthError
from app.services.schwab_ingestion import SchwabNotConnectedError
from tests.factories import create_test_account, create_test_user

A_HASH = "HASH_FOR_USER_A"
B_HASH = "HASH_FOR_USER_B"


async def _headers(db: AsyncSession, user) -> dict:
    token, _ = AuthService(db)._create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


async def _link(db: AsyncSession, user, account_id: int, account_hash: str):
    db.add(
        AccountLink(
            user_id=user.id,
            account_hash=account_hash,
            source="schwab_api",
            account_id=account_id,
            status=AccountLinkStatus.ACTIVE,
        )
    )
    await db.flush()


@pytest.fixture
def spy_pulls(monkeypatch, db: AsyncSession):
    """Replace both pull primitives with recorders that write a real run row.

    They close over the test session on purpose: a real ``BrokerImportRun`` in
    the test DB is what the response schema serializes, so the assertions below
    are about the row an actual pull would have produced - including the
    ``user_id`` it was stamped with, which is the isolation property under test.

    The recorded call list also proves the NEGATIVE cases: an endpoint that
    404s an unowned account must never have reached a pull at all.
    """
    calls: list[dict] = []

    def _make(kind: ImportKind, raises: Exception | None = None):
        async def _fake(user_id, account_hash, *args, **kwargs):
            calls.append(
                {
                    "kind": kind,
                    "user_id": user_id,
                    "account_hash": account_hash,
                    # A real pull is handed NO caller session (session
                    # ownership); assert the trigger honors that. BOTH are
                    # recorded: capturing only kwargs would let a
                    # positionally-passed session slip through unnoticed.
                    "session_factory": kwargs.get("session_factory"),
                    "extra_args": args,
                    "extra_kwargs": {
                        k: v for k, v in kwargs.items() if k != "session_factory"
                    },
                }
            )
            if raises is not None:
                raise raises
            run = BrokerImportRun(
                user_id=user_id,
                account_hash=account_hash,
                source="schwab_api",
                kind=kind,
                status=ImportStatus.COMPLETE,
                item_count=3,
                created_at=datetime.now(timezone.utc),
            )
            db.add(run)
            await db.flush()
            return run

        return _fake

    def _install(*, positions_raises=None, transactions_raises=None):
        monkeypatch.setattr(
            schwab_ingestion,
            "pull_positions",
            _make(ImportKind.POSITIONS, positions_raises),
        )
        monkeypatch.setattr(
            schwab_ingestion,
            "pull_transactions",
            _make(ImportKind.TRANSACTIONS, transactions_raises),
        )
        return calls

    _install.calls = calls
    return _install


class TestImportTriggerGates:
    async def test_requires_auth(self, client: AsyncClient):
        r = await client.post("/api/v1/accounts/1/import", json={})
        assert r.status_code in (401, 403)

    async def test_unknown_account_404(
        self, authed_client: AsyncClient, spy_pulls
    ):
        calls = spy_pulls()
        r = await authed_client.post("/api/v1/accounts/999999/import", json={})
        assert r.status_code == 404
        assert calls == []

    async def test_account_without_link_409(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, spy_pulls
    ):
        calls = spy_pulls()
        account = await create_test_account(db, test_user, name="Unlinked")
        r = await authed_client.post(
            f"/api/v1/accounts/{account.id}/import", json={}
        )
        assert r.status_code == 409
        assert "link" in r.json()["detail"].lower()
        # No link means no hash means no pull was ever attempted.
        assert calls == []

    async def test_demo_mode_blocks_the_import(
        self,
        authed_client: AsyncClient,
        db: AsyncSession,
        test_user,
        spy_pulls,
        monkeypatch,
    ):
        calls = spy_pulls()
        monkeypatch.setattr("app.core.demo.settings.DEMO_MODE", True)
        account = await create_test_account(db, test_user, name="Demo")
        await _link(db, test_user, account.id, A_HASH)
        r = await authed_client.post(
            f"/api/v1/accounts/{account.id}/import", json={}
        )
        assert r.status_code == 403
        assert calls == []


class TestImportTriggerBehavior:
    async def test_default_pulls_both_kinds(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, spy_pulls
    ):
        calls = spy_pulls()
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id, A_HASH)

        r = await authed_client.post(
            f"/api/v1/accounts/{account.id}/import", json={}
        )
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["account_id"] == account.id
        assert [run["kind"] for run in data["runs"]] == [
            "positions",
            "transactions",
        ]
        assert all(run["status"] == "complete" for run in data["runs"])
        assert [c["kind"] for c in calls] == [
            ImportKind.POSITIONS,
            ImportKind.TRANSACTIONS,
        ]

    async def test_kind_selects_one_pull(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, spy_pulls
    ):
        calls = spy_pulls()
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id, A_HASH)

        r = await authed_client.post(
            f"/api/v1/accounts/{account.id}/import",
            json={"kind": "transactions"},
        )
        assert r.status_code == 201
        assert [c["kind"] for c in calls] == [ImportKind.TRANSACTIONS]

    async def test_pull_is_never_handed_a_caller_session(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, spy_pulls
    ):
        """SESSION OWNERSHIP: the pulls create their own sessions and must not
        receive the request-scoped one (committing it would flush unrelated
        pending state). The trigger passes no session_factory at all."""
        calls = spy_pulls()
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id, A_HASH)

        await authed_client.post(f"/api/v1/accounts/{account.id}/import", json={})
        assert calls, "expected the pulls to have been called"
        assert all(c["session_factory"] is None for c in calls)
        # Nothing extra was passed at all - so no session reached them
        # positionally either.
        assert all(c["extra_args"] == () for c in calls)
        assert all(c["extra_kwargs"] == {} for c in calls)

    async def test_not_connected_maps_to_409(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, spy_pulls
    ):
        spy_pulls(
            positions_raises=SchwabNotConnectedError(
                "Schwab token has passed its 7-day expiry; reconnect required"
            )
        )
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id, A_HASH)

        r = await authed_client.post(
            f"/api/v1/accounts/{account.id}/import", json={}
        )
        assert r.status_code == 409
        assert "reconnect" in r.json()["detail"].lower()

    async def test_schwab_failure_maps_to_502(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, spy_pulls
    ):
        spy_pulls(positions_raises=SchwabAPIError("Schwab returned HTTP 500"))
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id, A_HASH)

        r = await authed_client.post(
            f"/api/v1/accounts/{account.id}/import", json={}
        )
        assert r.status_code == 502

    async def test_auth_failure_maps_to_502(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, spy_pulls
    ):
        spy_pulls(positions_raises=SchwabAuthError("Schwab rejected the token"))
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id, A_HASH)

        r = await authed_client.post(
            f"/api/v1/accounts/{account.id}/import", json={}
        )
        assert r.status_code == 502

    async def test_positions_success_survives_a_transactions_failure(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, spy_pulls
    ):
        """ATOMICITY: each pull is its own transaction and the two kinds are
        independent, so a positions snapshot that landed is never unwound by a
        later transactions failure."""
        spy_pulls(transactions_raises=SchwabAPIError("boom"))
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id, A_HASH)

        r = await authed_client.post(
            f"/api/v1/accounts/{account.id}/import", json={}
        )
        assert r.status_code == 502

        kept = (
            await db.execute(
                select(BrokerImportRun).where(
                    BrokerImportRun.user_id == test_user.id,
                    BrokerImportRun.kind == ImportKind.POSITIONS,
                )
            )
        ).scalars().all()
        assert len(kept) == 1
        assert kept[0].status == ImportStatus.COMPLETE


class TestImportTriggerCrossUserIsolation:
    """The audit's #1 bar, on the one endpoint that reaches a broker."""

    @pytest.fixture
    async def two_users(self, db: AsyncSession):
        a = await create_test_user(db, email="import-a@example.com")
        b = await create_test_user(db, email="import-b@example.com")
        return a, b

    async def test_b_cannot_import_into_a_account(
        self, client: AsyncClient, db: AsyncSession, two_users, spy_pulls
    ):
        calls = spy_pulls()
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        await _link(db, a, a_account.id, A_HASH)
        hb = await _headers(db, b)

        r = await client.post(
            f"/api/v1/accounts/{a_account.id}/import", json={}, headers=hb
        )
        # Indistinguishable from "no such account" - B learns nothing.
        assert r.status_code == 404
        # And, critically, no broker call was ever issued on A's behalf.
        assert calls == []

    async def test_pull_receives_the_authenticated_user_and_own_hash(
        self, client: AsyncClient, db: AsyncSession, two_users, spy_pulls
    ):
        calls = spy_pulls()
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        b_account = await create_test_account(db, b, name="B Roth")
        await _link(db, a, a_account.id, A_HASH)
        await _link(db, b, b_account.id, B_HASH)

        ha = await _headers(db, a)
        r = await client.post(
            f"/api/v1/accounts/{a_account.id}/import",
            json={"kind": "positions"},
            headers=ha,
        )
        assert r.status_code == 201
        assert len(calls) == 1
        assert calls[0]["user_id"] == a.id
        assert calls[0]["account_hash"] == A_HASH
        # B's identity and hash never appear anywhere in the call.
        assert calls[0]["user_id"] != b.id
        assert calls[0]["account_hash"] != B_HASH

    async def test_runs_written_are_scoped_to_the_importing_user(
        self, client: AsyncClient, db: AsyncSession, two_users, spy_pulls
    ):
        spy_pulls()
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        await _link(db, a, a_account.id, A_HASH)
        ha = await _headers(db, a)

        await client.post(
            f"/api/v1/accounts/{a_account.id}/import",
            json={"kind": "positions"},
            headers=ha,
        )

        b_runs = (
            await db.execute(
                select(BrokerImportRun).where(BrokerImportRun.user_id == b.id)
            )
        ).scalars().all()
        assert b_runs == []

    async def test_b_cannot_import_using_a_link_by_sharing_the_hash(
        self, client: AsyncClient, db: AsyncSession, two_users, spy_pulls
    ):
        """Even if B links the SAME broker hash to B's own account, the pull is
        issued as B and can only ever write B's rows - the hash is not an
        authority, ``user_id`` is."""
        calls = spy_pulls()
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        b_account = await create_test_account(db, b, name="B Roth")
        await _link(db, a, a_account.id, A_HASH)
        await _link(db, b, b_account.id, A_HASH)  # same hash string, B's row

        hb = await _headers(db, b)
        r = await client.post(
            f"/api/v1/accounts/{b_account.id}/import",
            json={"kind": "positions"},
            headers=hb,
        )
        assert r.status_code == 201
        assert calls[0]["user_id"] == b.id

        a_runs = (
            await db.execute(
                select(BrokerImportRun).where(BrokerImportRun.user_id == a.id)
            )
        ).scalars().all()
        assert a_runs == [], "B's import must not have written anything as A"


class TestHistoryHorizonIsDocumented:
    """The 60-day horizon is the reason the CSV path exists; it must stay a
    named constant, not a literal buried in a query."""

    def test_limit_constant_is_sixty_days(self):
        assert schwab_ingestion.TRANSACTION_HISTORY_LIMIT_DAYS == 60

    def test_gap_note_prefix_is_shared(self):
        note = schwab_ingestion._history_gap_note(
            datetime.now(timezone.utc) - timedelta(days=400),
            datetime.now(timezone.utc) - timedelta(days=59),
        )
        assert note.startswith(schwab_ingestion.HISTORY_GAP_NOTE_PREFIX)
        assert "recovery path" in note
