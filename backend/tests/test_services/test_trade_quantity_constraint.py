"""DB-level regression tests for ``ck_trades_quantity_positive`` (AE10).

The point of these tests is that they bypass every application guard. The API
layer already rejects quantity <= 0 (``schemas/trade.py`` uses
``Field(..., gt=0)``, exercised elsewhere), so an assertion that goes through
``TradeService``/HTTP proves nothing about the database. These insert straight
into the ``trades`` table - ORM add/flush and raw SQL - so the only thing that
can reject them is Postgres itself.

Also pinned here: ``price`` is deliberately NOT constrained (a zero cost basis
is legitimate - vested RSU, gift, spin-off). If someone later adds a
``price > 0`` constraint without running the pre-check against prod, the
zero-price test below fails and says why.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import Trade, TradeType
from tests.factories import create_test_equity

CONSTRAINT_NAME = "ck_trades_quantity_positive"


def _now() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=1)


def _trade(user_id, equity_id, *, quantity, price="10", trade_type=TradeType.BUY) -> Trade:
    return Trade(
        user_id=user_id,
        equity_id=equity_id,
        trade_type=trade_type,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fees=Decimal("0"),
        executed_at=_now(),
    )


class TestConstraintExists:
    async def test_check_constraint_is_defined_on_trades(self, db: AsyncSession):
        """The guard is a real DB CHECK constraint, not application code."""
        clause = await db.scalar(
            text(
                "SELECT pg_get_constraintdef(c.oid) "
                "FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE t.relname = 'trades' AND c.conname = :name AND c.contype = 'c'"
            ),
            {"name": CONSTRAINT_NAME},
        )
        assert clause is not None, (
            f"{CONSTRAINT_NAME} is missing from the trades table. The model "
            "(app/db/models/trade.py) and migration 20260729_001 must both "
            "declare it."
        )
        assert "quantity" in clause and ">" in clause


class TestQuantityRejectedAtTheDatabase:
    @pytest.mark.parametrize("quantity", ["0", "-1", "-0.00000001"])
    async def test_orm_insert_is_rejected(self, db: AsyncSession, test_user, quantity):
        equity = await create_test_equity(db, symbol="QTY")
        db.add(_trade(test_user.id, equity.id, quantity=quantity))
        with pytest.raises(IntegrityError) as exc_info:
            await db.flush()
        assert CONSTRAINT_NAME in str(exc_info.value)

    @pytest.mark.parametrize(
        "trade_type", [TradeType.BUY, TradeType.SELL, TradeType.SHORT, TradeType.COVER]
    )
    async def test_rejected_for_every_direction(self, db: AsyncSession, test_user, trade_type):
        """Direction lives in trade_type, so no trade type may carry a
        negative quantity - a short is not "a buy of -N"."""
        equity = await create_test_equity(db, symbol=f"D{trade_type.value[:3].upper()}")
        db.add(_trade(test_user.id, equity.id, quantity="-5", trade_type=trade_type))
        with pytest.raises(IntegrityError) as exc_info:
            await db.flush()
        assert CONSTRAINT_NAME in str(exc_info.value)

    async def test_raw_sql_insert_is_rejected(self, db: AsyncSession, test_user):
        """The backstop holds for a writer that never touches the ORM either -
        a seed script, an import job, or a human in psql."""
        equity = await create_test_equity(db, symbol="RAWQ")
        with pytest.raises(IntegrityError) as exc_info:
            await db.execute(
                text(
                    "INSERT INTO trades "
                    "(user_id, equity_id, trade_type, quantity, price, fees, executed_at) "
                    "VALUES (:user_id, :equity_id, 'buy', 0, 10, 0, :executed_at)"
                ),
                {"user_id": test_user.id, "equity_id": equity.id, "executed_at": _now()},
            )
        assert CONSTRAINT_NAME in str(exc_info.value)

    async def test_update_to_non_positive_is_rejected(self, db: AsyncSession, test_user):
        """The constraint covers UPDATEs, not just INSERTs."""
        equity = await create_test_equity(db, symbol="UPDQ")
        trade = _trade(test_user.id, equity.id, quantity="10")
        db.add(trade)
        await db.flush()

        trade.quantity = Decimal("0")
        with pytest.raises(IntegrityError) as exc_info:
            await db.flush()
        assert CONSTRAINT_NAME in str(exc_info.value)


class TestStillAccepted:
    async def test_positive_quantity_is_accepted(self, db: AsyncSession, test_user):
        equity = await create_test_equity(db, symbol="OKQ")
        db.add(_trade(test_user.id, equity.id, quantity="0.00000001"))
        await db.flush()
        stored = await db.scalar(
            select(Trade.quantity).where(Trade.equity_id == equity.id)
        )
        assert stored == Decimal("0.00000001")

    async def test_zero_price_is_still_allowed(self, db: AsyncSession, test_user):
        """Deliberate: a zero cost basis is legitimate (vested RSU, gifted or
        inherited shares, a spin-off lot). The price > 0 constraint is parked
        in alembic/deferred/ until the pre-check
        (scripts/check_trade_constraint_violations.py) has been run against
        prod. If this test starts failing, a price constraint was applied -
        confirm that gate was actually cleared before "fixing" the test.
        """
        equity = await create_test_equity(db, symbol="RSU")
        db.add(_trade(test_user.id, equity.id, quantity="100", price="0"))
        await db.flush()
        stored = await db.scalar(select(Trade.price).where(Trade.equity_id == equity.id))
        assert stored == Decimal("0")
