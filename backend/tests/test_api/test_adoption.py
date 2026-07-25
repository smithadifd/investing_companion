"""Tests for the §2 adoption endpoint
(POST /api/v1/accounts/{account_id}/reconciliation/adopt) and its detach
companion (POST /api/v1/trades/{trade_id}/detach).

Covers the brief's required matrix: delta>0 -> BUY, delta<0 -> SELL, delta==0 ->
no trade, replay idempotency, a new run with further drift -> a second
adjustment, zero-crossing/negative -> manual review (no trade), the synthetic
edit-422 + detach flow, delete of a synthetic trade, the demo guard, user
scoping, plus the §3 estimated-basis quote fallback and the no-link/never-
imported 409 guards.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

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

HASH = "ADOPT_HASH"


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


async def _seed_run(
    db, user, positions, *, status=ImportStatus.COMPLETE,
    account_hash=HASH, created_at=None,
):
    """positions: list of (symbol, asset_type, quantity, average_price)."""
    run = BrokerImportRun(
        user_id=user.id, account_hash=account_hash, source="schwab_api",
        kind=ImportKind.POSITIONS, status=status, created_at=created_at or _now(),
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


async def _trade(authed_client, symbol, qty, price, account_id, *, trade_type="buy", days_ago=5):
    executed = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return await authed_client.post("/api/v1/trades", json={
        "symbol": symbol, "trade_type": trade_type, "quantity": str(qty),
        "price": str(price), "executed_at": executed, "account_id": account_id,
    })


async def _make_account(authed_client, name="Roth"):
    return (
        await authed_client.post("/api/v1/accounts", json={"name": name})
    ).json()["data"]


async def _adopt(authed_client, account_id):
    return await authed_client.post(
        f"/api/v1/accounts/{account_id}/reconciliation/adopt"
    )


class TestAdoptGuards:
    async def test_requires_auth(self, client: AsyncClient):
        assert (
            await client.post("/api/v1/accounts/1/reconciliation/adopt")
        ).status_code == 401

    async def test_no_active_link_409(self, authed_client: AsyncClient):
        acct = await _make_account(authed_client)
        assert (await _adopt(authed_client, acct["id"])).status_code == 409

    async def test_unknown_account_404(self, authed_client: AsyncClient):
        assert (await _adopt(authed_client, 999999)).status_code == 404

    async def test_never_imported_409(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = await _make_account(authed_client)
        await _link(db, test_user, acct["id"])  # active link, no complete run
        await db.commit()
        assert (await _adopt(authed_client, acct["id"])).status_code == 409

    async def test_other_users_account_404(
        self, authed_client: AsyncClient, db: AsyncSession
    ):
        other = await create_test_user(db, email="other-adopt@example.com")
        other_acct = await create_test_account(db, other, name="Theirs")
        await _link(db, other, other_acct.id)
        await _seed_run(db, other, [("AAPL", "EQUITY", 1, 10)])
        await db.commit()
        assert (await _adopt(authed_client, other_acct.id)).status_code == 404

    async def test_demo_user_cannot_adopt(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, monkeypatch
    ):
        acct = await _make_account(authed_client)
        await _link(db, test_user, acct["id"])
        await _seed_run(db, test_user, [("AAPL", "EQUITY", 1, 10)])
        await db.commit()
        import app.core.demo as demo
        monkeypatch.setattr(demo, "is_demo_mode", lambda: True)
        assert (await _adopt(authed_client, acct["id"])).status_code == 403


class TestAdoptDeltas:
    async def test_positive_delta_creates_buy(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = await _make_account(authed_client)
        await create_test_equity(db, symbol="AAPL")
        await _trade(authed_client, "AAPL", 8, 100, acct["id"])
        await _link(db, test_user, acct["id"])
        run = await _seed_run(db, test_user, [("AAPL", "EQUITY", 10, 150)])
        run_id = run.id
        await db.commit()

        resp = await _adopt(authed_client, acct["id"])
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["source_import_run_id"] == run_id
        assert data["skipped"] == []
        assert len(data["adopted"]) == 1
        row = data["adopted"][0]
        assert row["symbol"] == "AAPL"
        assert row["trade_type"] == "buy"
        assert Decimal(row["quantity"]) == Decimal("2")
        assert Decimal(row["price"]) == Decimal("150")
        assert row["basis_is_estimated"] is False
        assert row["status"] == "created"

        # The created trade carries the provenance stamps (§2).
        t = (
            await authed_client.get(f"/api/v1/trades/{row['trade_id']}")
        ).json()["data"]
        assert t["is_synthetic"] is True
        assert t["source"] == "schwab_api"
        assert t["basis_is_estimated"] is False
        assert t["source_import_run_id"] == run_id
        assert t["trade_type"] == "buy"
        assert Decimal(t["quantity"]) == Decimal("2")

        # WYSIWYG: reconciliation now shows the symbol matched (delta 0).
        recon = (
            await authed_client.get(f"/api/v1/accounts/{acct['id']}/reconciliation")
        ).json()["data"]
        aapl = {p["symbol"]: p for p in recon["positions"]}["AAPL"]
        assert Decimal(aapl["quantity_delta"]) == Decimal("0")

    async def test_negative_delta_creates_sell(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = await _make_account(authed_client)
        await create_test_equity(db, symbol="GOOG")
        await _trade(authed_client, "GOOG", 5, 50, acct["id"])
        await _link(db, test_user, acct["id"])
        await _seed_run(db, test_user, [("GOOG", "EQUITY", 3, 60)])
        await db.commit()

        data = (await _adopt(authed_client, acct["id"])).json()["data"]
        assert len(data["adopted"]) == 1
        row = data["adopted"][0]
        assert row["trade_type"] == "sell"
        assert Decimal(row["quantity"]) == Decimal("2")
        assert Decimal(row["price"]) == Decimal("60")
        assert row["status"] == "created"

    async def test_zero_delta_writes_nothing(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = await _make_account(authed_client)
        await create_test_equity(db, symbol="MSFT")
        await _trade(authed_client, "MSFT", 10, 100, acct["id"])
        await _link(db, test_user, acct["id"])
        await _seed_run(db, test_user, [("MSFT", "EQUITY", 10, 100)])
        await db.commit()

        data = (await _adopt(authed_client, acct["id"])).json()["data"]
        assert data["adopted"] == []
        assert data["skipped"] == []
        # No trades were written beyond the one manual buy.
        trades = (await authed_client.get("/api/v1/trades")).json()["data"]
        assert len(trades) == 1
        assert trades[0]["is_synthetic"] is False

    async def test_estimated_basis_uses_quote_fallback(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, monkeypatch
    ):
        """§3: null Schwab average_price -> current quote, basis_is_estimated."""
        from app.services.equity import EquityService

        async def fake_quote(self, symbol):
            return SimpleNamespace(price=Decimal("140"))

        monkeypatch.setattr(EquityService, "get_quote", fake_quote)

        acct = await _make_account(authed_client)
        await create_test_equity(db, symbol="NVDA")
        await _trade(authed_client, "NVDA", 4, 100, acct["id"])
        await _link(db, test_user, acct["id"])
        await _seed_run(db, test_user, [("NVDA", "EQUITY", 6, None)])
        await db.commit()

        data = (await _adopt(authed_client, acct["id"])).json()["data"]
        row = data["adopted"][0]
        assert row["trade_type"] == "buy"
        assert Decimal(row["quantity"]) == Decimal("2")
        assert Decimal(row["price"]) == Decimal("140")
        assert row["basis_is_estimated"] is True
        t = (
            await authed_client.get(f"/api/v1/trades/{row['trade_id']}")
        ).json()["data"]
        assert t["basis_is_estimated"] is True


class TestAdoptIdempotencyAndDrift:
    async def test_replay_is_idempotent(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = await _make_account(authed_client)
        await create_test_equity(db, symbol="AAPL")
        await _trade(authed_client, "AAPL", 8, 100, acct["id"])
        await _link(db, test_user, acct["id"])
        await _seed_run(db, test_user, [("AAPL", "EQUITY", 10, 150)])
        await db.commit()

        first = (await _adopt(authed_client, acct["id"])).json()["data"]
        assert len(first["adopted"]) == 1

        # Re-adopt against the same run: delta is now 0, so no new trade and no
        # 500 - idempotent-safe.
        second_resp = await _adopt(authed_client, acct["id"])
        assert second_resp.status_code == 201
        second = second_resp.json()["data"]
        assert second["adopted"] == []
        assert second["skipped"] == []

        # Exactly one synthetic trade exists.
        trades = (await authed_client.get("/api/v1/trades")).json()["data"]
        synthetic = [t for t in trades if t["is_synthetic"]]
        assert len(synthetic) == 1

    async def test_new_run_with_further_drift_allows_second_adjustment(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = await _make_account(authed_client)
        await create_test_equity(db, symbol="AAPL")
        await _trade(authed_client, "AAPL", 8, 100, acct["id"])
        await _link(db, test_user, acct["id"])
        run1 = await _seed_run(
            db, test_user, [("AAPL", "EQUITY", 10, 150)], created_at=_now(60)
        )
        run1_id = run1.id
        await db.commit()

        first = (await _adopt(authed_client, acct["id"])).json()["data"]
        assert first["source_import_run_id"] == run1_id
        assert len(first["adopted"]) == 1

        # A newer complete run shows further drift (15 now).
        run2 = await _seed_run(
            db, test_user, [("AAPL", "EQUITY", 15, 160)], created_at=_now(1)
        )
        run2_id = run2.id
        await db.commit()

        second = (await _adopt(authed_client, acct["id"])).json()["data"]
        assert second["source_import_run_id"] == run2_id
        assert len(second["adopted"]) == 1
        row = second["adopted"][0]
        assert row["status"] == "created"
        assert Decimal(row["quantity"]) == Decimal("5")  # 15 - 10

        # Two synthetic trades now (one per run).
        trades = (await authed_client.get("/api/v1/trades")).json()["data"]
        synthetic = sorted(
            (t for t in trades if t["is_synthetic"]),
            key=lambda t: t["source_import_run_id"],
        )
        assert len(synthetic) == 2
        assert {t["source_import_run_id"] for t in synthetic} == {run1_id, run2_id}


class TestAdoptManualReview:
    async def test_negative_schwab_quantity_flagged_not_adopted(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = await _make_account(authed_client)
        await create_test_equity(db, symbol="SHRT")
        await _trade(authed_client, "SHRT", 5, 100, acct["id"])
        await _link(db, test_user, acct["id"])
        await _seed_run(db, test_user, [("SHRT", "EQUITY", -3, 100)])
        await db.commit()

        data = (await _adopt(authed_client, acct["id"])).json()["data"]
        assert data["adopted"] == []
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["symbol"] == "SHRT"
        assert data["skipped"][0]["reason"] == "manual_review"
        # No synthetic trade written.
        trades = (await authed_client.get("/api/v1/trades")).json()["data"]
        assert all(not t["is_synthetic"] for t in trades)

    async def test_ic_short_zero_crossing_flagged(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = await _make_account(authed_client)
        await create_test_equity(db, symbol="ZC")
        # IC is short 5; Schwab reports long 3 -> reconciling crosses zero.
        await _trade(authed_client, "ZC", 5, 100, acct["id"], trade_type="short")
        await _link(db, test_user, acct["id"])
        await _seed_run(db, test_user, [("ZC", "EQUITY", 3, 100)])
        await db.commit()

        data = (await _adopt(authed_client, acct["id"])).json()["data"]
        assert data["adopted"] == []
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["reason"] == "manual_review"

    async def test_ineligible_asset_class_flagged(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        acct = await _make_account(authed_client)
        await _link(db, test_user, acct["id"])
        await _seed_run(db, test_user, [("OPT", "OPTION", 2, 7)])
        await db.commit()

        data = (await _adopt(authed_client, acct["id"])).json()["data"]
        assert data["adopted"] == []
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["reason"] == "ineligible"


class TestSyntheticEditAndDetachEndpoints:
    async def _adopt_one_buy(self, authed_client, db, test_user):
        acct = await _make_account(authed_client)
        await create_test_equity(db, symbol="EDIT")
        await _trade(authed_client, "EDIT", 8, 100, acct["id"])
        await _link(db, test_user, acct["id"])
        await _seed_run(db, test_user, [("EDIT", "EQUITY", 10, 150)])
        await db.commit()
        data = (await _adopt(authed_client, acct["id"])).json()["data"]
        return data["adopted"][0]["trade_id"]

    async def test_edit_protected_fields_422(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        tid = await self._adopt_one_buy(authed_client, db, test_user)
        for body in (
            {"quantity": "9"},
            {"price": "99"},
            {"trade_type": "sell"},
            {"executed_at": "2026-01-01T00:00:00Z"},
        ):
            resp = await authed_client.put(f"/api/v1/trades/{tid}", json=body)
            assert resp.status_code == 422, body

    async def test_edit_notes_allowed(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        tid = await self._adopt_one_buy(authed_client, db, test_user)
        resp = await authed_client.put(
            f"/api/v1/trades/{tid}", json={"notes": "checked"}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["notes"] == "checked"

    async def test_detach_then_edit_succeeds(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        tid = await self._adopt_one_buy(authed_client, db, test_user)
        detached = await authed_client.post(f"/api/v1/trades/{tid}/detach")
        assert detached.status_code == 200
        d = detached.json()["data"]
        assert d["is_synthetic"] is False
        assert d["source_import_run_id"] is None

        edited = await authed_client.put(
            f"/api/v1/trades/{tid}", json={"quantity": "9"}
        )
        assert edited.status_code == 200
        assert Decimal(edited.json()["data"]["quantity"]) == Decimal("9")

    async def test_detach_idempotent(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        tid = await self._adopt_one_buy(authed_client, db, test_user)
        assert (await authed_client.post(f"/api/v1/trades/{tid}/detach")).status_code == 200
        # Second detach on the now-manual trade is a no-op 200.
        assert (await authed_client.post(f"/api/v1/trades/{tid}/detach")).status_code == 200

    async def test_detach_unknown_404(self, authed_client: AsyncClient):
        assert (
            await authed_client.post("/api/v1/trades/999999/detach")
        ).status_code == 404

    async def test_detach_blocked_in_demo(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, monkeypatch
    ):
        tid = await self._adopt_one_buy(authed_client, db, test_user)
        import app.core.demo as demo
        monkeypatch.setattr(demo, "is_demo_mode", lambda: True)
        assert (
            await authed_client.post(f"/api/v1/trades/{tid}/detach")
        ).status_code == 403

    async def test_delete_synthetic_allowed(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        tid = await self._adopt_one_buy(authed_client, db, test_user)
        assert (await authed_client.delete(f"/api/v1/trades/{tid}")).status_code == 204
        assert (await authed_client.get(f"/api/v1/trades/{tid}")).status_code == 404
