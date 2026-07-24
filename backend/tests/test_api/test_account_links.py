"""Tests for AccountLink model constraints and the link/list endpoints
(schwab-adopt-semantics.md §1/§4).

Covers: the model's hash-identity unique constraint and the partial
one-active-link-per-account index; user-initiated linking; the confirmation
gate on an account that already has trades; rotation orphaning old links in one
transaction; and demo-blocking of the (mutating) link endpoint.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account_link import AccountLink, AccountLinkStatus
from app.services.account_link import (
    AccountLinkService,
    AccountNotFoundError,
    LinkNeedsConfirmationError,
)
from tests.factories import (
    create_test_account,
    create_test_equity,
    create_test_trade,
    create_test_user,
)


class TestAccountLinkModel:
    async def test_hash_identity_unique(self, db: AsyncSession, test_user):
        acct = await create_test_account(db, test_user, name="Roth")
        db.add(
            AccountLink(
                user_id=test_user.id, account_hash="HASH1", source="schwab_api",
                account_id=acct.id, status=AccountLinkStatus.ACTIVE,
            )
        )
        await db.flush()
        # Same (user, source, hash) again -> unique violation.
        db.add(
            AccountLink(
                user_id=test_user.id, account_hash="HASH1", source="schwab_api",
                account_id=None, status=AccountLinkStatus.ORPHANED,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_one_active_link_per_account_partial_unique(
        self, db: AsyncSession, test_user
    ):
        acct = await create_test_account(db, test_user, name="Roth")
        db.add(
            AccountLink(
                user_id=test_user.id, account_hash="HA", source="schwab_api",
                account_id=acct.id, status=AccountLinkStatus.ACTIVE,
            )
        )
        await db.flush()
        # A second ACTIVE link on the same account -> partial-index violation.
        db.add(
            AccountLink(
                user_id=test_user.id, account_hash="HB", source="schwab_api",
                account_id=acct.id, status=AccountLinkStatus.ACTIVE,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_orphaned_links_do_not_contend(
        self, db: AsyncSession, test_user
    ):
        """An orphaned link + an active link on the same account is allowed -
        the partial index only covers status='active'."""
        acct = await create_test_account(db, test_user, name="Roth")
        db.add(
            AccountLink(
                user_id=test_user.id, account_hash="HOLD", source="schwab_api",
                account_id=acct.id, status=AccountLinkStatus.ORPHANED,
            )
        )
        db.add(
            AccountLink(
                user_id=test_user.id, account_hash="HNEW", source="schwab_api",
                account_id=acct.id, status=AccountLinkStatus.ACTIVE,
            )
        )
        await db.flush()  # no error


class TestAccountLinkService:
    async def test_link_and_list(self, db: AsyncSession, test_user):
        service = AccountLinkService(db)
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()

        link = await service.link_account(test_user.id, acct.id, "HASHX")
        assert link.status == "active"
        assert link.account_id == acct.id

        listed = await service.list_links(test_user.id, acct.id)
        assert [r.account_hash for r in listed] == ["HASHX"]

    async def test_link_unknown_account_raises(self, db: AsyncSession, test_user):
        service = AccountLinkService(db)
        with pytest.raises(AccountNotFoundError):
            await service.link_account(test_user.id, 999999, "HASHZ")

    async def test_confirm_gate_when_account_has_trades(
        self, db: AsyncSession, test_user
    ):
        service = AccountLinkService(db)
        equity = await create_test_equity(db, symbol="CGATE")
        acct = await create_test_account(db, test_user, name="Roth")
        await create_test_trade(db, equity, test_user, account_id=acct.id)
        await db.commit()

        with pytest.raises(LinkNeedsConfirmationError) as exc:
            await service.link_account(test_user.id, acct.id, "HASHT")
        assert exc.value.trade_count == 1

        # With confirm, it goes through.
        link = await service.link_account(
            test_user.id, acct.id, "HASHT", confirm=True
        )
        assert link.status == "active"

    async def test_rotation_orphans_old_active_in_one_txn(
        self, db: AsyncSession, test_user
    ):
        service = AccountLinkService(db)
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()

        await service.link_account(test_user.id, acct.id, "HOLD1")
        await service.link_account(test_user.id, acct.id, "HNEW2")

        # Exactly one active link, and it's the new hash; the old one orphaned.
        active_count = await db.scalar(
            select(func.count(AccountLink.id)).where(
                AccountLink.user_id == test_user.id,
                AccountLink.account_id == acct.id,
                AccountLink.status == AccountLinkStatus.ACTIVE,
            )
        )
        assert active_count == 1
        active = await service.get_active_link(test_user.id, acct.id)
        assert active.account_hash == "HNEW2"

        links = await service.list_links(test_user.id, acct.id)
        by_hash = {r.account_hash: r.status for r in links}
        assert by_hash == {"HOLD1": "orphaned", "HNEW2": "active"}

    async def test_relinking_same_hash_is_idempotent(
        self, db: AsyncSession, test_user
    ):
        service = AccountLinkService(db)
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()

        first = await service.link_account(test_user.id, acct.id, "SAME")
        second = await service.link_account(test_user.id, acct.id, "SAME")
        assert first.id == second.id
        total = await db.scalar(
            select(func.count(AccountLink.id)).where(
                AccountLink.user_id == test_user.id
            )
        )
        assert total == 1


class TestAccountLinkEndpoints:
    async def test_requires_auth(self, client: AsyncClient):
        assert (await client.get("/api/v1/accounts/1/links")).status_code == 401
        assert (
            await client.post("/api/v1/accounts/1/links", json={"account_hash": "H"})
        ).status_code == 401

    async def test_link_and_list_roundtrip(self, authed_client: AsyncClient):
        acct = (
            await authed_client.post("/api/v1/accounts", json={"name": "Roth"})
        ).json()["data"]
        created = await authed_client.post(
            f"/api/v1/accounts/{acct['id']}/links", json={"account_hash": "ABC123"}
        )
        assert created.status_code == 201
        assert created.json()["data"]["status"] == "active"
        assert created.json()["data"]["account_hash"] == "ABC123"

        listed = await authed_client.get(f"/api/v1/accounts/{acct['id']}/links")
        assert listed.status_code == 200
        assert [r["account_hash"] for r in listed.json()["data"]] == ["ABC123"]

    async def test_link_unknown_account_404(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/accounts/999999/links", json={"account_hash": "H"}
        )
        assert resp.status_code == 404

    async def test_link_confirm_gate_409(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        await create_test_equity(db, symbol="EGATE")
        acct = (
            await authed_client.post("/api/v1/accounts", json={"name": "HasTrades"})
        ).json()["data"]
        await authed_client.post("/api/v1/trades", json={
            "symbol": "EGATE", "trade_type": "buy", "quantity": "3", "price": "10",
            "executed_at": "2026-06-01T00:00:00Z", "account_id": acct["id"],
        })

        blocked = await authed_client.post(
            f"/api/v1/accounts/{acct['id']}/links", json={"account_hash": "GH"}
        )
        assert blocked.status_code == 409
        ok = await authed_client.post(
            f"/api/v1/accounts/{acct['id']}/links",
            json={"account_hash": "GH", "confirm": True},
        )
        assert ok.status_code == 201

    async def test_link_blocked_in_demo_mode(
        self, authed_client: AsyncClient, monkeypatch
    ):
        acct = (
            await authed_client.post("/api/v1/accounts", json={"name": "Roth"})
        ).json()["data"]
        import app.core.demo as demo

        monkeypatch.setattr(demo, "is_demo_mode", lambda: True)
        resp = await authed_client.post(
            f"/api/v1/accounts/{acct['id']}/links", json={"account_hash": "H"}
        )
        assert resp.status_code == 403

    async def test_links_are_user_scoped(
        self, authed_client: AsyncClient, db: AsyncSession
    ):
        other = await create_test_user(db, email="other-link@example.com")
        other_acct = await create_test_account(db, other, name="Theirs")
        db.add(
            AccountLink(
                user_id=other.id, account_hash="THEIRS", source="schwab_api",
                account_id=other_acct.id, status=AccountLinkStatus.ACTIVE,
            )
        )
        await db.commit()
        # The other user's account isn't ours -> listing returns [] (no leak).
        listed = await authed_client.get(f"/api/v1/accounts/{other_acct.id}/links")
        assert listed.json()["data"] == []
