"""Service/model-level tests for §2 Trade provenance + the adoption mechanics
that don't need the HTTP layer.

Covers: create_trade provenance stamping (defaults + adoption kwargs), the
partial unique index enforcing one synthetic trade per (user, account, equity,
run), the update_trade synthetic-edit 422 guard + detach, delete of a synthetic
trade, and AdoptionService's IntegrityError-catch (a concurrent double-adopt is
reported already_adopted, never a 500).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account_link import AccountLink, AccountLinkStatus
from app.db.models.broker_import import (
    BrokerImportRun,
    ImportedPosition,
    ImportKind,
    ImportStatus,
)
from app.db.models.trade import Trade, TradeType
from app.schemas.trade import TradeCreate, TradeUpdate
from app.services.adoption import AdoptionService
from app.services.trade import TradeService
from tests.factories import (
    create_test_account,
    create_test_equity,
)


def _now(minutes_ago: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


async def _seed_run(db, user, positions, *, account_hash="PVHASH", status=ImportStatus.COMPLETE):
    run = BrokerImportRun(
        user_id=user.id, account_hash=account_hash, source="schwab_api",
        kind=ImportKind.POSITIONS, status=status, created_at=_now(),
    )
    db.add(run)
    await db.flush()
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


async def _link(db, user, account_id, account_hash="PVHASH"):
    db.add(
        AccountLink(
            user_id=user.id, account_hash=account_hash, source="schwab_api",
            account_id=account_id, status=AccountLinkStatus.ACTIVE,
        )
    )
    await db.flush()


class TestCreateTradeProvenance:
    async def test_defaults_are_manual_non_synthetic(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="MAN")
        svc = TradeService(db)
        resp = await svc.create_trade(
            test_user.id,
            TradeCreate(
                equity_id=equity.id, trade_type=TradeType.BUY,
                quantity=Decimal("1"), price=Decimal("10"),
                executed_at=_now(),
            ),
        )
        assert resp is not None
        assert resp.source == "manual"
        assert resp.is_synthetic is False
        assert resp.basis_is_estimated is False
        assert resp.source_import_run_id is None

    async def test_adoption_kwargs_are_stamped(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="SYN")
        run = await _seed_run(db, test_user, [("SYN", "EQUITY", 1, 10)])
        svc = TradeService(db)
        resp = await svc.create_trade(
            test_user.id,
            TradeCreate(
                equity_id=equity.id, trade_type=TradeType.BUY,
                quantity=Decimal("1"), price=Decimal("10"), executed_at=_now(),
            ),
            source="schwab_api", is_synthetic=True, basis_is_estimated=True,
            source_import_run_id=run.id,
        )
        assert resp is not None
        assert resp.source == "schwab_api"
        assert resp.is_synthetic is True
        assert resp.basis_is_estimated is True
        assert resp.source_import_run_id == run.id


class TestSyntheticIdempotencyIndex:
    async def test_duplicate_synthetic_same_run_raises(
        self, db: AsyncSession, test_user
    ):
        """Partial unique index: two synthetic trades for the same (user,
        account, equity, run) collide; non-synthetic rows never do."""
        equity = await create_test_equity(db, symbol="IDX")
        acct = await create_test_account(db, test_user, name="Roth")
        run = await _seed_run(db, test_user, [("IDX", "EQUITY", 2, 10)])

        def _mk(is_synthetic):
            return Trade(
                user_id=test_user.id, equity_id=equity.id,
                account_id=acct.id, trade_type=TradeType.BUY,
                quantity=Decimal("1"), price=Decimal("10"),
                fees=Decimal("0"), executed_at=_now(), is_synthetic=is_synthetic,
                source="schwab_api",
                source_import_run_id=run.id if is_synthetic else None,
            )

        db.add(_mk(True))
        await db.flush()
        db.add(_mk(True))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_non_synthetic_do_not_contend(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="IDX2")
        acct = await create_test_account(db, test_user, name="Roth")
        # Two ordinary manual trades on the same account/equity: no run id, not
        # synthetic -> the partial index never applies.
        for _ in range(2):
            db.add(
                Trade(
                    user_id=test_user.id, equity_id=equity.id,
                    account_id=acct.id, trade_type=TradeType.BUY,
                    quantity=Decimal("1"), price=Decimal("10"),
                    fees=Decimal("0"), executed_at=_now(),
                )
            )
        await db.flush()  # no error


class TestSyntheticEditGuardAndDetach:
    async def _make_synthetic(self, db, user):
        equity = await create_test_equity(db, symbol="EDIT")
        acct = await create_test_account(db, user, name="Roth")
        run = await _seed_run(db, user, [("EDIT", "EQUITY", 5, 10)])
        trade = Trade(
            user_id=user.id, equity_id=equity.id, account_id=acct.id,
            trade_type=TradeType.BUY, quantity=Decimal("5"), price=Decimal("10"),
            fees=Decimal("0"), executed_at=_now(), is_synthetic=True,
            source="schwab_api", source_import_run_id=run.id,
        )
        db.add(trade)
        await db.flush()
        return trade

    @pytest.mark.parametrize(
        "update",
        [
            TradeUpdate(quantity=Decimal("9")),
            TradeUpdate(price=Decimal("99")),
            TradeUpdate(trade_type=TradeType.SELL),
            TradeUpdate(executed_at=_now(1)),
        ],
    )
    async def test_edit_protected_field_raises(
        self, db: AsyncSession, test_user, update
    ):
        trade = await self._make_synthetic(db, test_user)
        svc = TradeService(db)
        with pytest.raises(ValueError, match="synthetic"):
            await svc.update_trade(trade.id, test_user.id, update)

    async def test_edit_notes_allowed_on_synthetic(
        self, db: AsyncSession, test_user
    ):
        trade = await self._make_synthetic(db, test_user)
        svc = TradeService(db)
        resp = await svc.update_trade(
            trade.id, test_user.id, TradeUpdate(notes="reviewed")
        )
        assert resp is not None
        assert resp.notes == "reviewed"
        assert resp.is_synthetic is True  # still synthetic

    async def test_detach_then_edit_succeeds(
        self, db: AsyncSession, test_user
    ):
        trade = await self._make_synthetic(db, test_user)
        svc = TradeService(db)

        detached = await svc.detach_trade(trade.id, test_user.id)
        assert detached is not None
        assert detached.is_synthetic is False
        assert detached.source_import_run_id is None

        # Now the protected edit goes through.
        edited = await svc.update_trade(
            trade.id, test_user.id, TradeUpdate(quantity=Decimal("9"))
        )
        assert edited is not None
        assert edited.quantity == Decimal("9")

    async def test_detach_is_idempotent(self, db: AsyncSession, test_user):
        trade = await self._make_synthetic(db, test_user)
        svc = TradeService(db)
        await svc.detach_trade(trade.id, test_user.id)
        # Second detach on the now-manual trade is a no-op 200.
        again = await svc.detach_trade(trade.id, test_user.id)
        assert again is not None
        assert again.is_synthetic is False

    async def test_detach_unknown_trade_returns_none(
        self, db: AsyncSession, test_user
    ):
        svc = TradeService(db)
        assert await svc.detach_trade(999999, test_user.id) is None

    async def test_delete_synthetic_allowed(self, db: AsyncSession, test_user):
        trade = await self._make_synthetic(db, test_user)
        svc = TradeService(db)
        assert await svc.delete_trade(trade.id, test_user.id) is True
        remaining = await db.scalar(
            select(func.count(Trade.id)).where(Trade.id == trade.id)
        )
        assert remaining == 0


class TestAdoptionIntegrityRace:
    async def test_double_adopt_reports_already_adopted_not_500(
        self, db: AsyncSession, test_user
    ):
        """Simulate a concurrent adopt that committed first: a synthetic trade
        for (user, account, equity, run) already exists, but our recomputed
        delta is still non-zero (a stale read). create_trade's commit hits the
        partial unique index; AdoptionService catches it and reports
        already_adopted rather than raising a 500."""
        equity = await create_test_equity(db, symbol="RACE")
        acct = await create_test_account(db, test_user, name="Roth")
        # Schwab reports 12; IC manual holds 8.
        run = await _seed_run(db, test_user, [("RACE", "EQUITY", 12, 100)])
        await _link(db, test_user, acct.id)
        db.add(
            Trade(
                user_id=test_user.id, equity_id=equity.id, account_id=acct.id,
                trade_type=TradeType.BUY, quantity=Decimal("8"),
                price=Decimal("90"), fees=Decimal("0"), executed_at=_now(20),
            )
        )
        # A synthetic trade for THIS run already exists (the "won the race"
        # writer) but only plugged 2, so IC=10 and delta is still 2.
        winner = Trade(
            user_id=test_user.id, equity_id=equity.id, account_id=acct.id,
            trade_type=TradeType.BUY, quantity=Decimal("2"), price=Decimal("100"),
            fees=Decimal("0"), executed_at=_now(1), is_synthetic=True,
            source="schwab_api", source_import_run_id=run.id,
        )
        db.add(winner)
        await db.commit()

        # Capture ids before adopt(): its internal rollback (on the caught
        # IntegrityError) expires these ORM handles, so read them out first.
        user_id, equity_id, acct_id, run_id = (
            test_user.id, equity.id, acct.id, run.id
        )
        winner_id = winner.id

        result = await AdoptionService(db).adopt(user_id, acct_id)

        assert len(result.adopted) == 1
        row = result.adopted[0]
        assert row.symbol == "RACE"
        assert row.status == "already_adopted"
        assert row.trade_id == winner_id

        # Still exactly one synthetic trade for this key - no duplicate written.
        count = await db.scalar(
            select(func.count(Trade.id)).where(
                Trade.user_id == user_id,
                Trade.equity_id == equity_id,
                Trade.source_import_run_id == run_id,
                Trade.is_synthetic.is_(True),
            )
        )
        assert count == 1
