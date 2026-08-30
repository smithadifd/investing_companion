"""Surface 4 - the NAV / total-return view.

SEAM UNDER TEST: the **NAV seam** - ``NavService.get_nav``. A deep interface
(one ``NavSummary`` out) over a fold that spans the cash ledger, the position
fold and ``trade_pairs``. It is a SEPARATE surface from ``get_portfolio`` on
purpose: widening ``PortfolioSummary`` would make every dashboard render pay
for the cash fold, and the existing hot path stays untouched.

The honesty flag is the point of half these tests. ``_calculate_positions``
sets ``current_value = None`` when a quote lookup fails, and the cash ledger
cannot know a balance from before its coverage starts. NAV must say so rather
than silently reading a missing input as zero.

Quotes are stubbed at the ``EquityService.get_quote`` seam - a genuine
external boundary (it reaches Yahoo/Stooq/Alpha Vantage), not an internal
collaborator.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.cash import CashTransaction
from app.db.models.trade import TradeType
from app.services.nav import NavService
from tests.factories import create_test_account, create_test_equity, create_test_trade


def _at(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


class _Quote:
    def __init__(self, price):
        self.price = Decimal(str(price)) if price is not None else None


def _stub_quotes(service: NavService, prices: dict[str, object]) -> None:
    """Pin the quote boundary. A symbol mapped to None models a failed lookup
    (a dead provider chain), which is the input NAV must flag rather than zero."""

    async def _get_quote(symbol: str):
        if symbol not in prices:
            return None
        value = prices[symbol]
        return None if value is None else _Quote(value)

    service.trades.equity_service.get_quote = _get_quote  # type: ignore[method-assign]


async def _cash(db, user, account, kind, amount, days_ago):
    db.add(
        CashTransaction(
            user_id=user.id,
            account_id=account.id,
            kind=kind,
            amount=Decimal(str(amount)),
            occurred_at=_at(days_ago),
        )
    )
    await db.flush()


async def _trade(db, equity, user, ttype, qty, price, days_ago, account_id, fees="0"):
    return await create_test_trade(
        db, equity, user,
        trade_type=ttype,
        quantity=Decimal(str(qty)),
        price=Decimal(str(price)),
        fees=Decimal(str(fees)),
        executed_at=_at(days_ago),
        account_id=account_id,
    )


class TestNavArithmetic:
    async def test_nav_is_cash_plus_market_value(self, db: AsyncSession, test_user):
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="NAVA")
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "10000", 60)
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 50, acct.id)
        await db.commit()

        service = NavService(db)
        _stub_quotes(service, {"NAVA": 150})
        nav = await service.get_nav(test_user.id, acct.id)

        assert nav is not None
        assert nav.cash_balance == Decimal("9000")
        assert nav.positions_market_value == Decimal("1500")
        assert nav.nav == Decimal("10500")
        assert nav.net_contributions == Decimal("10000")
        assert nav.unrealized_pnl == Decimal("500")
        assert nav.realized_pnl == Decimal("0")
        assert nav.is_estimated is False
        assert nav.estimate_reasons == []

    async def test_total_return_is_absolute_dollars(self, db: AsyncSession, test_user):
        """Q-A: the headline is the absolute dollar figure, not a percentage."""
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="NAVB")
        service = NavService(db)
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "10000", 60)
        await _trade(db, equity, test_user, TradeType.BUY, 20, 100, 50, acct.id)
        await _trade(db, equity, test_user, TradeType.SELL, 10, 130, 40, acct.id)
        await _trade(db, equity, test_user, TradeType.DIVIDEND, 10, "2.00", 30, acct.id)
        await db.commit()
        await service.trades._recalculate_pairs(test_user.id, equity.id)

        _stub_quotes(service, {"NAVB": 150})
        nav = await service.get_nav(test_user.id, acct.id)

        assert nav is not None
        assert nav.realized_pnl == Decimal("300")  # 10 x (130 - 100)
        assert nav.unrealized_pnl == Decimal("500")  # 10 x (150 - 100)
        assert nav.dividends_received == Decimal("20")
        assert nav.total_return_amount == Decimal("820")
        # 820 / 10000
        assert nav.total_return_percent == Decimal("8.20")

    async def test_percent_is_null_without_contributions(
        self, db: AsyncSession, test_user
    ):
        """Dividing by zero contributions would be a fabricated percentage."""
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="NAVC")
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 50, acct.id)
        await db.commit()

        service = NavService(db)
        _stub_quotes(service, {"NAVC": 150})
        nav = await service.get_nav(test_user.id, acct.id)
        assert nav is not None
        assert nav.net_contributions == Decimal("0")
        assert nav.total_return_percent is None
        assert nav.total_return_amount == Decimal("500")

    async def test_fees_are_reported_but_not_subtracted_twice(
        self, db: AsyncSession, test_user
    ):
        """This engine's realized P&L is ALREADY net of the matched legs' fees
        and its cost basis already carries the opening fee, so subtracting
        fees_paid again would double-count them. fees_paid is reported for
        transparency; total_return_amount does not re-apply it."""
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="NAVF")
        service = NavService(db)
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "10000", 60)
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 50, acct.id, fees="10")
        await _trade(db, equity, test_user, TradeType.SELL, 10, 130, 40, acct.id, fees="5")
        await db.commit()
        await service.trades._recalculate_pairs(test_user.id, equity.id)

        _stub_quotes(service, {})
        nav = await service.get_nav(test_user.id, acct.id)
        assert nav is not None
        assert nav.fees_paid == Decimal("15")
        # 300 gross less BOTH commissions, counted exactly once.
        assert nav.realized_pnl == Decimal("285")
        assert nav.total_return_amount == Decimal("285")
        # And the cash actually in the account agrees.
        assert nav.cash_balance == Decimal("10000") - Decimal("1010") + Decimal("1295")

    async def test_scope_is_one_account(self, db: AsyncSession, test_user):
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(db, test_user, name="Taxable", display_order=1)
        equity = await create_test_equity(db, symbol="NAVS")
        await _cash(db, test_user, roth, TradeType.DEPOSIT, "5000", 60)
        await _cash(db, test_user, taxable, TradeType.DEPOSIT, "9000", 60)
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 50, roth.id)
        await db.commit()

        service = NavService(db)
        _stub_quotes(service, {"NAVS": 100})
        roth_nav = await service.get_nav(test_user.id, roth.id)
        taxable_nav = await service.get_nav(test_user.id, taxable.id)
        assert roth_nav is not None and taxable_nav is not None
        assert roth_nav.nav == Decimal("5000")
        assert roth_nav.account is not None and roth_nav.account.name == "Roth"
        assert taxable_nav.nav == Decimal("9000")
        assert taxable_nav.positions_market_value == Decimal("0")

    async def test_whole_ledger_scope_sums_every_account(
        self, db: AsyncSession, test_user
    ):
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(db, test_user, name="Taxable", display_order=1)
        equity = await create_test_equity(db, symbol="NAVT")
        await _cash(db, test_user, roth, TradeType.DEPOSIT, "5000", 60)
        await _cash(db, test_user, taxable, TradeType.DEPOSIT, "9000", 60)
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 50, roth.id)
        await db.commit()

        service = NavService(db)
        _stub_quotes(service, {"NAVT": 120})
        nav = await service.get_nav(test_user.id, None)
        assert nav is not None
        assert nav.account_id is None and nav.account is None
        assert nav.cash_balance == Decimal("13000")
        assert nav.positions_market_value == Decimal("1200")
        assert nav.nav == Decimal("14200")
        assert nav.net_contributions == Decimal("14000")

    async def test_unknown_account_returns_none(self, db: AsyncSession, test_user):
        await db.commit()
        service = NavService(db)
        assert await service.get_nav(test_user.id, 999_999) is None


class TestNavHonesty:
    async def test_a_missing_quote_is_flagged_never_zeroed(
        self, db: AsyncSession, test_user
    ):
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="NOQUOTE")
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "10000", 60)
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 50, acct.id)
        await db.commit()

        service = NavService(db)
        _stub_quotes(service, {"NOQUOTE": None})
        nav = await service.get_nav(test_user.id, acct.id)

        assert nav is not None
        assert nav.is_estimated is True
        assert any("NOQUOTE" in reason for reason in nav.estimate_reasons)
        # The position is excluded from market value rather than valued at 0 -
        # and the flag is what tells the reader the NAV is short by it.
        assert nav.positions_market_value == Decimal("0")

    async def test_an_unknown_opening_balance_is_flagged(
        self, db: AsyncSession, test_user
    ):
        """Q-E: Schwab's transaction history reaches 60 days. Anything the
        ledger cannot see before that is unknown, not zero."""
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="OLDACC")
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 400, acct.id)
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "1000", 30)
        await db.commit()

        service = NavService(db)
        _stub_quotes(service, {"OLDACC": 100})
        nav = await service.get_nav(test_user.id, acct.id)

        assert nav is not None
        assert nav.is_estimated is True
        assert nav.coverage.opening_balance_is_known is False
        assert any("opening" in reason for reason in nav.estimate_reasons)

    async def test_an_inconsistent_ledger_is_flagged(
        self, db: AsyncSession, test_user
    ):
        """More closed than was ever opened: the walk knows it disagrees with
        net quantity, so the basis behind unrealized P&L is untrustworthy."""
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="BADLEDGER")
        await _trade(db, equity, test_user, TradeType.BUY, 5, 100, 50, acct.id)
        await _trade(db, equity, test_user, TradeType.SELL, 8, 120, 40, acct.id)
        await db.commit()

        service = NavService(db)
        _stub_quotes(service, {"BADLEDGER": 100})
        nav = await service.get_nav(test_user.id, acct.id)
        assert nav is not None
        assert nav.is_estimated is True
        assert any("ledger" in reason for reason in nav.estimate_reasons)

    async def test_a_quiet_empty_account_is_not_estimated(
        self, db: AsyncSession, test_user
    ):
        """Nothing has happened, so nothing is unknown - the flag must not
        cry wolf on a brand-new account."""
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()

        service = NavService(db)
        _stub_quotes(service, {})
        nav = await service.get_nav(test_user.id, acct.id)
        assert nav is not None
        assert nav.is_estimated is False
        assert nav.nav == Decimal("0")
