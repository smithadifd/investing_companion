"""NAV / total-return service - Surface 4 of the total-return design.

A SEPARATE surface from ``get_portfolio``, deliberately. ``PortfolioSummary``
is consumed by the dashboard and by ``usePortfolio`` on the trades page;
widening it would make every dashboard render pay for the cash fold. Keeping
NAV as its own endpoint leaves the existing hot path untouched, which is the
same reasoning the trade-readiness plan used for its DB-only endpoint.

This module composes rather than extends: it holds a ``TradeService`` and a
``CashLedgerService`` and folds their answers together. Neither of them learns
anything about NAV.

HONESTY IS THE FEATURE. Three inputs can be missing, and NAV reports each one
instead of reading it as zero:

* a failed quote lookup (``_calculate_positions`` sets ``current_value=None``),
* an opening balance from before the cash ledger's coverage begins (Q-E: the
  Schwab backfill reaches 60 days and no further),
* an inconsistent FIFO ledger (``OpenLots.ledger_inconsistent`` - more closed
  than was ever opened), which makes the basis behind unrealized P&L
  untrustworthy.

Same spirit as ``schemas/reconciliation.py``'s "show it, flag it" rule and the
alert-staleness precedent from ``20260814_001``: unknown reads as unknown.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import Account
from app.schemas.account import AccountRef
from app.schemas.cash import CashCoverage, NavSummary
from app.services.cash import CashLedgerService
from app.services.trade import OpenLots, TradeService

_CENTS = Decimal("0.01")


class NavService:
    """Builds the NAV / total-return view for one account or the whole ledger."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.trades = TradeService(db)
        self.cash = CashLedgerService(db)

    async def get_nav(
        self, user_id: UUID, account_id: int | None = None
    ) -> NavSummary | None:
        """NAV for ``account_id``, or for the WHOLE user ledger when it is None.

        ``account_id=None`` means every account plus the unassigned trade
        bucket - NOT "the unassigned bucket", which is what a bare
        ``account_id=None`` means in ``TradeService._calculate_positions``. The
        conventions differ because cash has no unassigned bucket
        (``cash_transactions.account_id`` is NOT NULL), and the difference is
        the reason ``CashLedgerService`` takes a *list* of account ids.

        Returns ``None`` when a named account is not this user's - the caller
        maps that to 404, never a 500 and never someone else's numbers.
        """
        account_obj: Account | None = None
        if account_id is not None:
            account_obj = await self.db.scalar(
                select(Account).where(
                    Account.id == account_id, Account.user_id == user_id
                )
            )
            if account_obj is None:
                return None

        scope = None if account_id is None else [account_id]
        reasons: list[str] = []

        # Positions are always computed per (account, equity) so one code path
        # serves both scopes; the account scope just filters the result.
        positions = await self.trades._calculate_positions(
            user_id, with_quotes=True, by_account=True
        )
        if account_id is not None:
            positions = [p for p in positions if p.account_id == account_id]
        open_positions = [p for p in positions if p.quantity != 0]

        positions_market_value = Decimal("0")
        unrealized_pnl = Decimal("0")
        for p in open_positions:
            # One open-lot walk per open position, serving BOTH the
            # ledger-consistency check and the unrealized figure. That extra
            # query per position is why NAV is its own endpoint rather than a
            # widening of the dashboard's portfolio call.
            lots = await self.trades._get_open_lots(user_id, p.equity_id, p.account_id)
            if lots.ledger_inconsistent:
                reasons.append(
                    f"inconsistent ledger for {p.equity.symbol}: more shares were "
                    "closed than were ever opened, so its cost basis (and the "
                    "unrealized P&L derived from it) cannot be trusted"
                )
                continue

            if p.current_value is None or p.current_price is None:
                # Excluded from market value rather than valued at zero. The
                # flag is what tells the reader NAV is short by it.
                reasons.append(
                    f"no quote for {p.equity.symbol}: its market value is missing "
                    "from NAV, not counted as zero"
                )
                continue

            positions_market_value += p.current_value
            unrealized_pnl += self._unrealized_from_lots(lots, p.current_price)

        realized_pnl = sum((p.realized_pnl for p in positions), Decimal("0"))

        cash_balance = await self.cash.cash_balance(user_id, scope)
        net_contributions = await self.cash.net_contributions(user_id, scope)
        dividends_received = await self.cash.dividends_received(user_id, scope)
        fees_paid = await self.cash.fees_paid(user_id, scope)
        coverage = await self.cash.coverage(user_id, scope)

        if not coverage.opening_balance_is_known:
            reasons.append(self._coverage_reason(coverage))

        positions_market_value = positions_market_value.quantize(_CENTS)
        unrealized_pnl = unrealized_pnl.quantize(_CENTS)
        realized_pnl = Decimal(realized_pnl).quantize(_CENTS)

        # ABSOLUTE DOLLARS (Q-A). Fees are deliberately NOT subtracted again:
        # this engine's realized P&L is already net of BOTH matched legs'
        # commissions (services/trade.py, the SELL/COVER branches) and
        # avg_cost_basis already carries the opening fee, so unrealized is net
        # of it too. Dividends are already net of withholding. Re-applying
        # fees_paid here would double-count every commission in the book.
        # fees_paid stays on the response as a reported figure.
        total_return_amount = (
            realized_pnl + unrealized_pnl + dividends_received
        ).quantize(_CENTS)

        total_return_percent = None
        if net_contributions > 0:
            total_return_percent = (
                total_return_amount / net_contributions * Decimal("100")
            ).quantize(_CENTS)

        return NavSummary(
            account_id=account_id,
            account=AccountRef.model_validate(account_obj) if account_obj else None,
            cash_balance=cash_balance,
            positions_market_value=positions_market_value,
            nav=(cash_balance + positions_market_value).quantize(_CENTS),
            net_contributions=net_contributions,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            dividends_received=dividends_received,
            fees_paid=fees_paid,
            total_return_amount=total_return_amount,
            total_return_percent=total_return_percent,
            as_of=datetime.now(timezone.utc),
            is_estimated=bool(reasons),
            estimate_reasons=reasons,
            coverage=coverage,
        )

    @staticmethod
    def _coverage_reason(coverage: CashCoverage) -> str:
        """Say WHY the cash history is incomplete, not just that it is.

        Three distinguishable causes, and the reader can act on a different
        thing in each: re-run the import, enter the missing cash by hand, or
        accept the 60-day horizon. A single generic sentence for all three was
        the version that let an incomplete picture read as a complete one.
        """
        if coverage.complete_from is not None:
            detail = (
                f"the cash history is complete only from "
                f"{coverage.complete_from.date()} — the broker import could not "
                "reach further back, so NAV is short every contribution made "
                "before that date"
            )
            if coverage.provenance_note:
                detail = f"{detail} ({coverage.provenance_note})"
            return detail
        if coverage.cash_starts_at is None:
            return (
                "no cash history has been recorded at all, so the cash balance "
                "and every contribution-based figure start from zero rather "
                "than from what was actually in the account"
            )
        return (
            f"the cash history starts {coverage.cash_starts_at.date()} but "
            f"trading activity starts {coverage.first_activity_at.date()} — the "
            "opening balance before the ledger begins is unknown, so NAV is "
            "short whatever cash was in the account then"
        )

    @staticmethod
    def _unrealized_from_lots(lots: OpenLots, current_price: Decimal) -> Decimal:
        """Unrealized P&L over the still-open FIFO lots, net of their fees.

        DELIBERATELY NOT ``PositionSummary.unrealized_pnl``, and this is the
        one place NAV's arithmetic departs from the Positions tab's.

        ``_calculate_positions`` derives its average cost from a *net* running
        cost (it subtracts a sale's PROCEEDS, not the sold lots' cost), so
        after a profitable partial sale the remaining basis is pulled down and
        the gain is counted twice: once in ``realized_pnl`` from
        ``trade_pairs``, and again in a deflated ``unrealized_pnl``. Buy 20 at
        $100, sell 10 at $130, mark at $150 and that fold reports $800
        unrealized on top of $300 realized - $1,100 of "return" on $800 of
        actual gain.

        Summing ``realized + unrealized`` is exactly what a total-return figure
        does, so NAV needs the two to be DISJOINT. Reading unrealized off the
        FIFO open lots - the same lots the realized figure consumed the other
        half of - makes them so, and costs nothing extra because the walk has
        already been run for the consistency check.

        Consequence to know about: NAV's ``unrealized_pnl`` will differ from the
        Positions tab's for any position with a profitable partial sale behind
        it. The portfolio hot path is deliberately left alone (design doc,
        Surface 4), so this is a real difference between two surfaces, not a
        rounding artefact.

        Fees ride along the same way ``_recalculate_pairs`` treats them: the
        matched share of the opening commission is netted out, so an open lot
        carries its own unamortised fee.
        """
        total = Decimal("0")
        for _tid, qty, price, _at, fee_ps in lots.long_lots:
            total += qty * (current_price - price) - qty * fee_ps
        for _tid, qty, price, _at, fee_ps in lots.short_lots:
            total += qty * (price - current_price) - qty * fee_ps
        return total
