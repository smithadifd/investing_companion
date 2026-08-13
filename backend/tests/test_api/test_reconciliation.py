"""Tests for the read-only §6 reconciliation endpoint
(GET /api/v1/accounts/{account_id}/reconciliation).

Covers the account-level envelope (last_import_at / never_imported /
newer_failed_import_at), the per-symbol union rows (Schwab-only, IC-only, both),
that quantity_delta is NEVER null, §5 eligibility flagging (OPTION greyed not
dropped), §3 ledger_inconsistent, and the link/ownership gates (409 without an
active link, 404 for an account that isn't the user's).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account_link import AccountLink, AccountLinkStatus
from app.db.models.broker_import import (
    BrokerImportRun,
    ImportedPosition,
    ImportKind,
    ImportStatus,
)
from tests.factories import (
    create_test_account,
    create_test_equity,
    create_test_user,
)

HASH = "RECON_HASH"


def _now(minutes_ago: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


async def _link(db, user, account_id, account_hash=HASH):
    db.add(
        AccountLink(
            user_id=user.id, account_hash=account_hash, source="schwab_api",
            account_id=account_id, status=AccountLinkStatus.ACTIVE,
        )
    )
    await db.flush()


async def _seed_positions_run(
    db, user, positions, *, status=ImportStatus.COMPLETE,
    account_hash=HASH, created_at=None,
):
    """Create one positions run + its ImportedPosition rows.

    ``positions``: list of (symbol, asset_type, quantity, average_price).
    """
    run = BrokerImportRun(
        user_id=user.id, account_hash=account_hash, source="schwab_api",
        kind=ImportKind.POSITIONS, status=status,
        created_at=created_at or _now(),
    )
    db.add(run)
    await db.flush()
    if status == ImportStatus.COMPLETE:
        for symbol, asset_type, qty, avg in positions:
            db.add(
                ImportedPosition(
                    import_run_id=run.id, user_id=user.id, account_hash=account_hash,
                    source="schwab_api", symbol=symbol, asset_type=asset_type,
                    quantity=Decimal(str(qty)),
                    long_quantity=Decimal(str(qty)) if qty >= 0 else Decimal("0"),
                    short_quantity=Decimal("0") if qty >= 0 else Decimal(str(-qty)),
                    average_price=None if avg is None else Decimal(str(avg)),
                    raw={},
                )
            )
    await db.flush()
    return run


async def _ic_buy(authed_client, symbol, qty, price, account_id, days_ago=5):
    executed = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return await authed_client.post("/api/v1/trades", json={
        "symbol": symbol, "trade_type": "buy", "quantity": str(qty),
        "price": str(price), "executed_at": executed, "account_id": account_id,
    })


class TestReconciliationEndpoint:
    async def test_requires_auth(self, client: AsyncClient):
        assert (
            await client.get("/api/v1/accounts/1/reconciliation")
        ).status_code == 401

    async def test_no_active_link_409(
        self, authed_client: AsyncClient
    ):
        acct = (
            await authed_client.post("/api/v1/accounts", json={"name": "Roth"})
        ).json()["data"]
        resp = await authed_client.get(
            f"/api/v1/accounts/{acct['id']}/reconciliation"
        )
        assert resp.status_code == 409

    async def test_unknown_account_404(self, authed_client: AsyncClient):
        resp = await authed_client.get(
            "/api/v1/accounts/999999/reconciliation"
        )
        assert resp.status_code == 404

    async def test_other_users_account_404(
        self, authed_client: AsyncClient, db: AsyncSession
    ):
        other = await create_test_user(db, email="other-recon@example.com")
        other_acct = await create_test_account(db, other, name="Theirs")
        await _link(db, other, other_acct.id)
        await db.commit()
        resp = await authed_client.get(
            f"/api/v1/accounts/{other_acct.id}/reconciliation"
        )
        assert resp.status_code == 404

    async def test_linked_with_imports_populates_positions(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = (
            await authed_client.post("/api/v1/accounts", json={"name": "Roth"})
        ).json()["data"]
        await create_test_equity(db, symbol="AAPL")
        await create_test_equity(db, symbol="GOOG")
        # IC side: AAPL 8 @ 100 (both sides), GOOG 3 @ 50 (IC-only).
        await _ic_buy(authed_client, "AAPL", 8, 100, acct["id"])
        await _ic_buy(authed_client, "GOOG", 3, 50, acct["id"])
        # Schwab side: AAPL 10@150, MSFT 5@300 (Schwab-only), OPT OPTION 2.
        await _link(db, test_user, acct["id"])
        await _seed_positions_run(db, test_user, [
            ("AAPL", "EQUITY", 10, 150),
            ("MSFT", "EQUITY", 5, 300),
            ("OPT", "OPTION", 2, 7),
        ])
        await db.commit()

        resp = await authed_client.get(
            f"/api/v1/accounts/{acct['id']}/reconciliation"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["never_imported"] is False
        assert data["last_import_at"] is not None
        assert data["newer_failed_import_at"] is None

        rows = {p["symbol"]: p for p in data["positions"]}
        assert set(rows) == {"AAPL", "GOOG", "MSFT", "OPT"}

        # quantity_delta is NEVER null on any row.
        assert all(p["quantity_delta"] is not None for p in data["positions"])

        aapl = rows["AAPL"]
        assert aapl["schwab_quantity"] == "10.00000000"
        assert aapl["ic_quantity"] == "8.00000000"
        assert Decimal(aapl["quantity_delta"]) == Decimal("2")
        assert aapl["eligible"] is True
        assert Decimal(aapl["schwab_basis"]) == Decimal("150")
        assert Decimal(aapl["ic_basis"]) == Decimal("100")
        assert Decimal(aapl["basis_delta"]) == Decimal("50")
        assert aapl["ledger_inconsistent"] is False

        msft = rows["MSFT"]
        assert Decimal(msft["schwab_quantity"]) == Decimal("5")
        assert msft["ic_quantity"] is None
        assert Decimal(msft["quantity_delta"]) == Decimal("5")
        assert msft["ic_basis"] is None
        assert msft["basis_delta"] is None

        goog = rows["GOOG"]
        assert goog["schwab_quantity"] is None
        assert Decimal(goog["ic_quantity"]) == Decimal("3")
        assert goog["asset_type"] is None
        assert goog["eligible"] is True  # IC-only defaults eligible (§5)
        assert Decimal(goog["quantity_delta"]) == Decimal("-3")
        assert Decimal(goog["ic_basis"]) == Decimal("50")
        assert goog["schwab_basis"] is None

        opt = rows["OPT"]
        assert opt["asset_type"] == "OPTION"
        assert opt["eligible"] is False
        assert opt["ineligible_reason"] == "asset_type OPTION not supported"
        assert Decimal(opt["quantity_delta"]) == Decimal("2")

    async def test_never_imported_banner_envelope(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = (
            await authed_client.post("/api/v1/accounts", json={"name": "Roth"})
        ).json()["data"]
        await create_test_equity(db, symbol="TSLA")
        await _ic_buy(authed_client, "TSLA", 4, 200, acct["id"])
        # Active link but NO complete run at all.
        await _link(db, test_user, acct["id"])
        await db.commit()

        resp = await authed_client.get(
            f"/api/v1/accounts/{acct['id']}/reconciliation"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["never_imported"] is True
        assert data["last_import_at"] is None

        rows = {p["symbol"]: p for p in data["positions"]}
        tsla = rows["TSLA"]
        assert tsla["schwab_quantity"] is None  # Schwab side empty, not error
        assert Decimal(tsla["ic_quantity"]) == Decimal("4")
        assert Decimal(tsla["quantity_delta"]) == Decimal("-4")
        assert tsla["quantity_delta"] is not None

    async def test_newer_failed_import_surfaced(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = (
            await authed_client.post("/api/v1/accounts", json={"name": "Roth"})
        ).json()["data"]
        await _link(db, test_user, acct["id"])
        # Complete run at T-10min, then a FAILED run at T-1min (newer).
        await _seed_positions_run(
            db, test_user, [("AAPL", "EQUITY", 1, 10)], created_at=_now(10)
        )
        await _seed_positions_run(
            db, test_user, [], status=ImportStatus.FAILED, created_at=_now(1)
        )
        await db.commit()

        resp = await authed_client.get(
            f"/api/v1/accounts/{acct['id']}/reconciliation"
        )
        data = resp.json()["data"]
        assert data["never_imported"] is False
        assert data["newer_failed_import_at"] is not None

    async def test_ledger_inconsistent_nulls_basis(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = (
            await authed_client.post("/api/v1/accounts", json={"name": "Roth"})
        ).json()["data"]
        await create_test_equity(db, symbol="BAD")
        # IC: buy 5 then sell 10 (more closed than opened) -> malformed ledger.
        await _ic_buy(authed_client, "BAD", 5, 100, acct["id"], days_ago=10)
        sell_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        await authed_client.post("/api/v1/trades", json={
            "symbol": "BAD", "trade_type": "sell", "quantity": "10", "price": "150",
            "executed_at": sell_at, "account_id": acct["id"],
        })
        await _link(db, test_user, acct["id"])
        await _seed_positions_run(db, test_user, [("BAD", "EQUITY", 3, 150)])
        await db.commit()

        resp = await authed_client.get(
            f"/api/v1/accounts/{acct['id']}/reconciliation"
        )
        data = resp.json()["data"]
        bad = {p["symbol"]: p for p in data["positions"]}["BAD"]
        assert bad["ledger_inconsistent"] is True
        assert bad["ic_basis"] is None
        assert bad["basis_delta"] is None
        assert bad["quantity_delta"] is not None  # still never null

    async def test_read_endpoint_not_demo_blocked(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, monkeypatch
    ):
        """The §6 view is read-only and must stay reachable in demo mode."""
        acct = (
            await authed_client.post("/api/v1/accounts", json={"name": "Roth"})
        ).json()["data"]
        await _link(db, test_user, acct["id"])
        await _seed_positions_run(db, test_user, [("AAPL", "EQUITY", 1, 10)])
        await db.commit()

        import app.core.demo as demo

        monkeypatch.setattr(demo, "is_demo_mode", lambda: True)
        resp = await authed_client.get(
            f"/api/v1/accounts/{acct['id']}/reconciliation"
        )
        assert resp.status_code == 200


class TestPositionsReconciliationCrossUserIsolation:
    """The audit's #1 bar on the §6 positions view.

    The link lookup, the imported-position read and the IC-side position walk
    are each filtered on user_id, so a broker ``account_hash`` is never itself
    an authority - two users may legitimately hold the same hash STRING (it is
    just an opaque token in a user-scoped column) and must still see only their
    own rows.
    """

    async def _headers(self, db, user) -> dict:
        from app.services.auth import AuthService

        token, _ = AuthService(db)._create_access_token(user.id)
        return {"Authorization": f"Bearer {token}"}

    async def test_same_broker_hash_does_not_leak_positions_across_users(
        self, client: AsyncClient, db: AsyncSession
    ):
        from tests.factories import create_test_account

        a = await create_test_user(db, email="recon-iso-a@example.com")
        b = await create_test_user(db, email="recon-iso-b@example.com")
        a_account = await create_test_account(db, a, name="A Roth")
        b_account = await create_test_account(db, b, name="B Roth")
        await _link(db, a, a_account.id, HASH)
        await _link(db, b, b_account.id, HASH)  # identical hash string

        await _seed_positions_run(db, a, [("AAPL", "EQUITY", 25, 100)])
        await db.commit()

        hb = await self._headers(db, b)
        resp = await client.get(
            f"/api/v1/accounts/{b_account.id}/reconciliation", headers=hb
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["never_imported"] is True
        assert data["positions"] == []

        ha = await self._headers(db, a)
        a_data = (
            await client.get(
                f"/api/v1/accounts/{a_account.id}/reconciliation", headers=ha
            )
        ).json()["data"]
        assert [p["symbol"] for p in a_data["positions"]] == ["AAPL"]

    async def test_b_cannot_adopt_into_a_account(
        self, client: AsyncClient, db: AsyncSession
    ):
        from tests.factories import create_test_account

        a = await create_test_user(db, email="adopt-iso-a@example.com")
        b = await create_test_user(db, email="adopt-iso-b@example.com")
        a_account = await create_test_account(db, a, name="A Roth")
        await _link(db, a, a_account.id, HASH)
        await _seed_positions_run(db, a, [("AAPL", "EQUITY", 25, 100)])
        await db.commit()

        hb = await self._headers(db, b)
        resp = await client.post(
            f"/api/v1/accounts/{a_account.id}/reconciliation/adopt", headers=hb
        )
        assert resp.status_code == 404
