"""Tests for account CRUD and user scoping."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import Trade
from tests.factories import (
    create_test_account,
    create_test_equity,
    create_test_trade,
    create_test_user,
)


class TestAccountEndpoints:
    async def test_requires_auth(self, client: AsyncClient):
        assert (await client.get("/api/v1/accounts")).status_code == 401
        assert (await client.post("/api/v1/accounts", json={"name": "X"})).status_code == 401

    async def test_crud_roundtrip(self, authed_client: AsyncClient):
        created = await authed_client.post("/api/v1/accounts", json={
            "name": "Roth",
            "broker": "Schwab",
            "account_type": "roth",
            "risk_profile": "aggressive",
            "display_order": 1,
        })
        assert created.status_code == 201
        body = created.json()["data"]
        assert body["name"] == "Roth"
        assert body["account_type"] == "roth"
        account_id = body["id"]

        listed = await authed_client.get("/api/v1/accounts")
        assert listed.status_code == 200
        assert any(a["id"] == account_id for a in listed.json()["data"])

        fetched = await authed_client.get(f"/api/v1/accounts/{account_id}")
        assert fetched.json()["data"]["broker"] == "Schwab"

        # Explicit null clears a nullable field; omitted fields stay put
        updated = await authed_client.put(f"/api/v1/accounts/{account_id}", json={
            "risk_profile": None,
        })
        assert updated.status_code == 200
        assert updated.json()["data"]["risk_profile"] is None
        assert updated.json()["data"]["broker"] == "Schwab"

        deleted = await authed_client.delete(f"/api/v1/accounts/{account_id}")
        assert deleted.status_code == 204
        assert (await authed_client.get(f"/api/v1/accounts/{account_id}")).status_code == 404

    async def test_ordered_by_display_order(self, authed_client: AsyncClient):
        await authed_client.post("/api/v1/accounts", json={"name": "B", "display_order": 2})
        await authed_client.post("/api/v1/accounts", json={"name": "A", "display_order": 1})
        names = [a["name"] for a in (await authed_client.get("/api/v1/accounts")).json()["data"]]
        assert names.index("A") < names.index("B")

    async def test_duplicate_name_conflicts(self, authed_client: AsyncClient):
        await authed_client.post("/api/v1/accounts", json={"name": "Taxable"})
        dup = await authed_client.post("/api/v1/accounts", json={"name": "Taxable"})
        assert dup.status_code == 409

    async def test_accounts_are_user_scoped(
        self, authed_client: AsyncClient, db: AsyncSession
    ):
        other = await create_test_user(db, email="other@example.com")
        other_account = await create_test_account(db, other, name="Their Roth")
        await db.commit()

        # The other user's account is invisible and unreachable
        listed = await authed_client.get("/api/v1/accounts")
        assert all(a["id"] != other_account.id for a in listed.json()["data"])
        assert (await authed_client.get(f"/api/v1/accounts/{other_account.id}")).status_code == 404

    async def test_trade_carries_and_reassigns_account(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        await create_test_equity(db, symbol="TASSIGN")
        account = (await authed_client.post(
            "/api/v1/accounts", json={"name": "Brokerage"}
        )).json()["data"]

        created = await authed_client.post("/api/v1/trades", json={
            "symbol": "TASSIGN",
            "trade_type": "buy",
            "quantity": "5",
            "price": "10",
            "executed_at": "2026-06-01T00:00:00Z",
            "account_id": account["id"],
        })
        assert created.status_code == 201
        trade = created.json()["data"]
        assert trade["account_id"] == account["id"]
        assert trade["account"]["name"] == "Brokerage"

        # Explicit null unassigns
        unassigned = await authed_client.put(
            f"/api/v1/trades/{trade['id']}", json={"account_id": None}
        )
        assert unassigned.json()["data"]["account_id"] is None

        # Reassigning to an unknown account is a 422, not a 500
        bad = await authed_client.put(
            f"/api/v1/trades/{trade['id']}", json={"account_id": 999999}
        )
        assert bad.status_code == 422

    async def test_portfolio_by_account_splits_positions(
        self, authed_client: AsyncClient, db: AsyncSession
    ):
        await create_test_equity(db, symbol="PFBA")
        a1 = (await authed_client.post("/api/v1/accounts", json={"name": "A1"})).json()["data"]
        a2 = (await authed_client.post("/api/v1/accounts", json={"name": "A2"})).json()["data"]
        for acct in (a1, a2):
            await authed_client.post("/api/v1/trades", json={
                "symbol": "PFBA", "trade_type": "buy", "quantity": "3", "price": "10",
                "executed_at": "2026-06-01T00:00:00Z", "account_id": acct["id"],
            })

        agg = await authed_client.get("/api/v1/trades/portfolio")
        per = await authed_client.get("/api/v1/trades/portfolio?by_account=true")
        agg_pfba = [p for p in agg.json()["data"]["positions"] if p["equity"]["symbol"] == "PFBA"]
        per_pfba = [p for p in per.json()["data"]["positions"] if p["equity"]["symbol"] == "PFBA"]
        assert len(agg_pfba) == 1
        assert len(per_pfba) == 2

    async def test_delete_leaves_trades_unassigned(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="ACDEL")
        account = await create_test_account(db, test_user, name="Closing")
        trade = await create_test_trade(db, equity, test_user, account_id=account.id)
        await db.commit()

        assert (await authed_client.delete(f"/api/v1/accounts/{account.id}")).status_code == 204

        # The trade survives, now unassigned (FK SET NULL)
        await db.refresh(trade)
        refreshed = await db.scalar(select(Trade).where(Trade.id == trade.id))
        assert refreshed is not None
        assert refreshed.account_id is None
