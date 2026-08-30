"""Trade service - business logic for trade operations and P&L calculation."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.account import Account
from app.db.models.equity import Equity
from app.db.models.trade import Trade, TradePair, TradeType
from app.schemas.account import AccountRef
from app.schemas.trade import (
    PerformanceByCategory,
    PerformanceMetrics,
    PerformanceReport,
    PortfolioSummary,
    PositionSizeRequest,
    PositionSizeResponse,
    PositionSummary,
    TradeCreate,
    TradeEquity,
    TradePairResponse,
    TradeResponse,
    TradeUpdate,
    validate_trade_shape,
)
from app.services.equity import EquityService


class SyntheticAdoptionConflictError(Exception):
    """A trade mutation collided with the partial unique adoption index
    ``uq_trades_synthetic_adoption`` (user, account, equity, import-run) WHERE
    is_synthetic.

    The one reachable trigger is reassigning a *synthetic* trade's ``account_id``
    to an account that already holds a synthetic trade for the same equity and
    import run - ``account_id`` is deliberately NOT in §2's edit-blocked set, so
    the reassign is permitted, but the index still forbids a duplicate. Caught
    at the commit boundary and surfaced as a 409 instead of an uncaught 500.
    """


def _fee_per_share(trade: Trade) -> Decimal:
    """Per-share commission for a trade.

    Fees are stored per whole order (``trade.fees``), but a single open can be
    closed across several closes (and one close can span several opens), so
    realized P&L nets out only the *matched* fraction of each leg's fee. Spread
    the fee evenly over the order's shares and let the caller multiply by the
    matched quantity. Guards the degenerate zero-quantity trade (no valid trade
    has one, but never divide by zero).
    """
    if not trade.quantity:
        return Decimal("0")
    return trade.fees / trade.quantity


# Each open lot: (trade_id, remaining_qty, price, executed_at, fee_per_share) -
# the same tuple shape _recalculate_pairs' FIFO queues carry.
OpenLot = tuple[int, Decimal, Decimal, datetime, Decimal]


def split_adjusted_lots(lots: list[OpenLot], ratio: Decimal) -> list[OpenLot]:
    """Re-denominate open FIFO lots across a stock split. Pure; returns a new list.

    THE SHARED LOT-MUTATION SEAM. ``_recalculate_pairs`` (the mutating walk)
    and ``_get_open_lots`` (its read-only clone) are a deliberate clone pair
    whose spec-pinned differences are documented at :meth:`_get_open_lots`.
    A split branch would be a *third* place they must agree, and drift there is
    a live correctness risk: ``_get_open_lots().basis()`` feeds the Schwab
    basis reconciliation, where a split-unaware basis reports false broker
    drift. So the transform lives here once and both walks call it.

    ``ratio`` is the split row's ``quantity`` - 4 for a 4:1, ``0.25`` for a 1:4
    reverse::

        remaining_qty  *= ratio
        price          /= ratio
        fee_per_share  /= ratio     # the fee was levied per PRE-split share

    ``trade_id`` and ``executed_at`` are untouched, so the lot keeps pointing
    at the original opening trade and ``holding_period_days`` stays honest.

    The correctness property is that **lot value is invariant**:
    ``remaining_qty * price`` is unchanged (exactly so for a ratio whose
    reciprocal is representable in base 10 - 4:1, 2:1, 1:4 - and to Decimal's
    28-significant-digit context otherwise, e.g. 3:1).

    An empty ``lots`` (a split dated before the first buy) is a no-op, not an
    error. ``ratio`` cannot be zero: ``ck_trades_quantity_positive`` forbids it
    at the DB.
    """
    if not lots:
        return []
    return [
        (trade_id, qty * ratio, price / ratio, executed_at, fee_ps / ratio)
        for trade_id, qty, price, executed_at, fee_ps in lots
    ]


def _fold_position(rows: list[Trade]) -> tuple[Decimal, Decimal]:
    """Fold an ordered run of ``trades`` rows into ``(net_quantity, total_cost)``.

    THE FAIL-CLOSED DISPATCH. This replaced a bare ``else`` that treated every
    unrecognised ``trade_type`` as a SELL/SHORT - so adding any member to the
    enum made new rows silently *subtract* shares and cost (a $120 dividend
    shrank the position). The dispatch is now exhaustive and raises on anything
    it was not taught, which is the whole point: the next new member must make
    a decision here rather than inherit a wrong one.

    ``rows`` must already be in ``(executed_at, id)`` order - a split only
    re-denominates the shares held *before* it.
    """
    net_quantity = Decimal("0")
    total_cost = Decimal("0")
    for t in rows:
        if t.trade_type in (TradeType.BUY, TradeType.COVER):
            net_quantity += t.quantity
            total_cost += t.quantity * t.price + t.fees
        elif t.trade_type in (TradeType.SELL, TradeType.SHORT):
            net_quantity -= t.quantity
            total_cost -= t.quantity * t.price - t.fees
        elif t.trade_type == TradeType.SPLIT:
            # Share count is re-denominated; what was paid for those shares
            # is not. Leaving total_cost alone is what keeps avg_cost_basis
            # (= total_cost / net_quantity) correct across the split.
            net_quantity *= t.quantity
        elif t.trade_type == TradeType.DIVIDEND:
            # Cash-only. Its cash leg is folded by CashLedgerService; adding
            # it to total_cost here would double-count it against the
            # position's basis.
            continue
        else:
            raise ValueError(
                f"Trade {t.id} carries trade_type {t.trade_type.value!r}, which "
                "has no equity leg and must not be stored in `trades` - it "
                "belongs in cash_transactions. Refusing to fold it into a "
                "position rather than guessing a direction."
            )
    return net_quantity, total_cost


@dataclass
class OpenLots:
    """The leftover (still-open) FIFO lots for one (account, equity), as read
    off the end of a walk cloned from ``_recalculate_pairs`` (§3).

    A normal position populates exactly one side. ``ledger_inconsistent`` is
    set when the walk saw more close quantity than the queue could match (a
    malformed ledger claiming more shares closed than were ever opened) - in
    that case ``basis()`` returns ``None`` rather than a number derived from a
    walk it knows disagrees with net quantity.
    """

    long_lots: list[OpenLot] = field(default_factory=list)
    short_lots: list[OpenLot] = field(default_factory=list)
    ledger_inconsistent: bool = False

    def basis(self) -> Decimal | None:
        """Weighted-average price of the open lots (long side if any open,
        else short side); ``None`` when flat or the ledger is inconsistent."""
        if self.ledger_inconsistent:
            return None
        lots = self.long_lots or self.short_lots
        total_qty = sum((lot[1] for lot in lots), Decimal("0"))
        if total_qty == 0:
            return None
        weighted = sum((lot[1] * lot[2] for lot in lots), Decimal("0"))
        return weighted / total_qty


class TradeService:
    """Service for trade-related operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.equity_service = EquityService(db)

    async def list_trades(
        self,
        user_id: UUID,
        equity_id: int | None = None,
        trade_type: TradeType | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        account_id: int | None = None,
        unassigned: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[TradeResponse], int]:
        """List trades with optional filters.

        ``account_id`` filters to one account; ``unassigned=True`` filters to
        trades with no account (account_id NULL).
        """
        conditions = [Trade.user_id == user_id]

        if equity_id:
            conditions.append(Trade.equity_id == equity_id)
        if trade_type:
            conditions.append(Trade.trade_type == trade_type)
        if start_date:
            conditions.append(Trade.executed_at >= start_date)
        if end_date:
            conditions.append(Trade.executed_at <= end_date)
        if unassigned:
            conditions.append(Trade.account_id.is_(None))
        elif account_id is not None:
            conditions.append(Trade.account_id == account_id)

        # Count total
        count_stmt = select(func.count(Trade.id)).where(and_(*conditions))
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        # Fetch trades
        stmt = (
            select(Trade)
            .options(selectinload(Trade.equity), selectinload(Trade.account))
            .where(and_(*conditions))
            .order_by(Trade.executed_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        trades = result.scalars().all()

        return [self._trade_to_response(t) for t in trades], total

    async def get_trade(self, trade_id: int, user_id: UUID) -> TradeResponse | None:
        """Get a single trade by ID."""
        stmt = (
            select(Trade)
            .options(selectinload(Trade.equity), selectinload(Trade.account))
            .where(Trade.id == trade_id, Trade.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        trade = result.scalar_one_or_none()

        if not trade:
            return None

        return self._trade_to_response(trade)

    async def create_trade(
        self,
        user_id: UUID,
        data: TradeCreate,
        *,
        source: str = "manual",
        is_synthetic: bool = False,
        basis_is_estimated: bool = False,
        source_import_run_id: int | None = None,
    ) -> TradeResponse | None:
        """Create a new trade and recalculate P&L pairs.

        The provenance keyword args are the ONLY new work §2 adoption adds on
        top of the ordinary manual-trade path (``TradeService.create_trade`` is
        the shared commit path - insert -> commit -> recalculate). They default
        to a plain manual trade, so the public create endpoint is unchanged and
        never exposes syntheticness to the request body. Adoption passes
        ``is_synthetic=True`` + the run/basis provenance; a violation of the
        partial unique index (a concurrent re-adopt against the same run) raises
        IntegrityError from the commit for the caller to treat as idempotent.
        """
        # Resolve equity
        equity = None
        if data.equity_id:
            stmt = select(Equity).where(Equity.id == data.equity_id)
            result = await self.db.execute(stmt)
            equity = result.scalar_one_or_none()
        elif data.symbol:
            equity = await self.equity_service.get_or_create_equity(data.symbol)

        if not equity:
            return None

        # An account_id, if given, must belong to this user.
        if data.account_id is not None and not await self._account_owned(
            user_id, data.account_id
        ):
            return None

        trade = Trade(
            user_id=user_id,
            equity_id=equity.id,
            trade_type=data.trade_type,
            quantity=data.quantity,
            price=data.price,
            fees=data.fees,
            executed_at=data.executed_at,
            notes=data.notes,
            watchlist_item_id=data.watchlist_item_id,
            account_id=data.account_id,
            source=source,
            is_synthetic=is_synthetic,
            basis_is_estimated=basis_is_estimated,
            source_import_run_id=source_import_run_id,
        )

        self.db.add(trade)
        await self.db.commit()
        await self.db.refresh(trade)

        # Recalculate P&L pairs for this equity
        await self._recalculate_pairs(user_id, equity.id)

        # Reload with equity + account
        stmt = (
            select(Trade)
            .options(selectinload(Trade.equity), selectinload(Trade.account))
            .where(Trade.id == trade.id)
        )
        result = await self.db.execute(stmt)
        trade = result.scalar_one()

        response = self._trade_to_response(trade)
        # A closing trade that brings the position to exactly zero is a
        # "position closed" event - the lesson-capture prompt keys off this.
        # Scoped to the trade's own account: zeroing the Roth position is a
        # close even if a taxable position in the same ticker remains open.
        if trade.is_closing:
            positions = await self._calculate_positions(
                user_id, equity_id=equity.id, with_quotes=False, by_account=True
            )
            response.position_closed = any(
                p.account_id == trade.account_id and p.quantity == 0
                for p in positions
            )
        return response

    async def update_trade(
        self, trade_id: int, user_id: UUID, data: TradeUpdate
    ) -> TradeResponse | None:
        """Update a trade and recalculate P&L pairs."""
        stmt = (
            select(Trade)
            .options(selectinload(Trade.equity), selectinload(Trade.account))
            .where(Trade.id == trade_id, Trade.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        trade = result.scalar_one_or_none()

        if not trade:
            return None

        # §2 edit/detach policy: a synthetic (adoption) trade must not have its
        # quantity/price/trade_type/executed_at hand-edited in place - that
        # would silently drift the row from what adoption computed while it
        # still claims (via source_import_run_id) to satisfy the idempotency
        # key, so a re-run would see "already adopted" and never re-heal it.
        # The caller must detach first (clears is_synthetic/source_import_run_id,
        # turning it into an ordinary manual trade). 422 via ValueError.
        if trade.is_synthetic:
            protected = ("trade_type", "quantity", "price", "executed_at")
            attempted = [
                f for f in protected
                if f in data.model_fields_set and getattr(data, f) is not None
            ]
            if attempted:
                raise ValueError(
                    "Cannot edit "
                    f"{'/'.join(protected)} of a synthetic (adoption) trade; "
                    "detach it first "
                    "(POST /api/v1/trades/{trade_id}/detach)."
                )

        # Validate the account before mutating anything (explicit null
        # unassigns; a given id must belong to this user).
        reassign_account = "account_id" in data.model_fields_set
        if reassign_account and data.account_id is not None and not await self._account_owned(
            user_id, data.account_id
        ):
            raise ValueError(f"Unknown account id: {data.account_id}")

        if data.trade_type is not None:
            trade.trade_type = data.trade_type
        if data.quantity is not None:
            trade.quantity = data.quantity
        if data.price is not None:
            trade.price = data.price
        if data.fees is not None:
            trade.fees = data.fees
        if data.executed_at is not None:
            trade.executed_at = data.executed_at
        if data.notes is not None:
            trade.notes = data.notes
        if data.watchlist_item_id is not None:
            trade.watchlist_item_id = data.watchlist_item_id
        if reassign_account:
            trade.account_id = data.account_id

        # Every TradeUpdate field is optional, so the (type, price, account)
        # rules can only be checked against the RESULTING row - e.g. a patch
        # that flips trade_type to `split` without also sending price=0, or
        # one that reassigns a split onto an account. ValueError -> 422 via
        # the endpoint's existing handler.
        validate_trade_shape(trade.trade_type, trade.price, trade.account_id)

        try:
            await self.db.commit()
        except IntegrityError as e:
            # The only mutation that can violate a constraint here is reassigning
            # a synthetic trade's account onto the partial unique adoption index
            # (account_id isn't in §2's blocked edit set). Roll back and surface
            # a clean 409 rather than letting an uncaught IntegrityError 500.
            await self.db.rollback()
            raise SyntheticAdoptionConflictError(
                "Reassigning this synthetic (adoption) trade to that account "
                "collides with an existing adoption trade for the same equity "
                "and import run. Detach the trade first, or choose another "
                "account."
            ) from e
        await self.db.refresh(trade)

        # Recalculate P&L pairs for this equity (partitioned by account)
        await self._recalculate_pairs(user_id, trade.equity_id)

        # Reload with account context for the response
        result = await self.db.execute(
            select(Trade)
            .options(selectinload(Trade.equity), selectinload(Trade.account))
            .where(Trade.id == trade.id)
        )
        return self._trade_to_response(result.scalar_one())

    async def delete_trade(self, trade_id: int, user_id: UUID) -> bool:
        """Delete a trade and recalculate P&L pairs."""
        stmt = select(Trade).where(Trade.id == trade_id, Trade.user_id == user_id)
        result = await self.db.execute(stmt)
        trade = result.scalar_one_or_none()

        if not trade:
            return False

        equity_id = trade.equity_id

        await self.db.delete(trade)
        await self.db.commit()

        # Recalculate P&L pairs for this equity
        await self._recalculate_pairs(user_id, equity_id)

        return True

    async def detach_trade(
        self, trade_id: int, user_id: UUID
    ) -> TradeResponse | None:
        """Detach a synthetic (adoption) trade into an ordinary manual trade.

        Clears ``is_synthetic`` and ``source_import_run_id`` (§2's explicit
        detach action) so the row can then be freely hand-edited via
        ``update_trade``. Owner-scoped; returns ``None`` (caller -> 404) when
        the trade isn't the user's or doesn't exist.

        Idempotent: detaching a row that is already non-synthetic is a no-op
        that returns the trade unchanged (200), never an error. Quantity/price/
        type are untouched, so FIFO pairs don't change - no recalculation.
        """
        stmt = (
            select(Trade)
            .options(selectinload(Trade.equity), selectinload(Trade.account))
            .where(Trade.id == trade_id, Trade.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        trade = result.scalar_one_or_none()

        if not trade:
            return None

        if trade.is_synthetic:
            trade.is_synthetic = False
            trade.source_import_run_id = None
            await self.db.commit()
            await self.db.refresh(trade)

        return self._trade_to_response(trade)

    async def get_position(self, user_id: UUID, equity_id: int) -> PositionSummary | None:
        """Get current position for a single equity."""
        positions = await self._calculate_positions(user_id, equity_id=equity_id)
        return positions[0] if positions else None

    async def get_open_positions(
        self, user_id: UUID, by_account: bool = False
    ) -> list[PositionSummary]:
        """Open positions without quote lookups - DB-only context for dashboard surfaces."""
        positions = await self._calculate_positions(
            user_id, with_quotes=False, by_account=by_account
        )
        return [p for p in positions if p.quantity != 0]

    async def get_portfolio(
        self, user_id: UUID, by_account: bool = False
    ) -> PortfolioSummary:
        """Get portfolio summary with all positions.

        With ``by_account`` the positions list is split per (account, equity);
        the rollup totals are summed from those disjoint partitions.
        """
        positions = await self._calculate_positions(user_id, by_account=by_account)

        # Sum up totals
        total_invested = sum(p.total_cost for p in positions)
        current_value = sum(p.current_value for p in positions if p.current_value is not None)
        total_unrealized = sum(p.unrealized_pnl for p in positions if p.unrealized_pnl is not None)
        total_realized = sum(p.realized_pnl for p in positions)

        # Count total trades
        count_stmt = select(func.count(Trade.id)).where(Trade.user_id == user_id)
        count_result = await self.db.execute(count_stmt)
        total_trades = count_result.scalar() or 0

        return PortfolioSummary(
            total_invested=total_invested,
            current_value=current_value if positions else None,
            total_unrealized_pnl=total_unrealized if positions else None,
            total_realized_pnl=total_realized,
            positions=positions,
            position_count=len([p for p in positions if p.quantity != 0]),
            total_trades=total_trades,
        )

    async def get_performance(
        self,
        user_id: UUID,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> PerformanceReport:
        """Calculate trading performance metrics."""
        conditions = [TradePair.user_id == user_id]
        if start_date:
            conditions.append(TradePair.calculated_at >= start_date)
        if end_date:
            conditions.append(TradePair.calculated_at <= end_date)

        # Fetch all trade pairs
        stmt = (
            select(TradePair)
            .options(
                selectinload(TradePair.equity),
                selectinload(TradePair.open_trade),
                selectinload(TradePair.close_trade),
            )
            .where(and_(*conditions))
            .order_by(TradePair.calculated_at)
        )
        result = await self.db.execute(stmt)
        pairs = result.scalars().all()

        # Calculate metrics
        metrics = self._calculate_metrics(pairs)

        # Group by sector
        by_sector = self._group_by_category(pairs, lambda p: p.equity.sector or "Unknown")

        # Group by equity
        by_equity = self._group_by_category(pairs, lambda p: p.equity.symbol)

        return PerformanceReport(
            metrics=metrics,
            by_sector=by_sector,
            by_equity=by_equity,
            period_start=start_date,
            period_end=end_date,
        )

    async def get_trade_pairs(
        self,
        user_id: UUID,
        equity_id: int | None = None,
        limit: int = 100,
    ) -> list[TradePairResponse]:
        """Get trade pairs (matched open/close trades)."""
        conditions = [TradePair.user_id == user_id]
        if equity_id:
            conditions.append(TradePair.equity_id == equity_id)

        stmt = (
            select(TradePair)
            .options(selectinload(TradePair.equity))
            .where(and_(*conditions))
            .order_by(TradePair.calculated_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        pairs = result.scalars().all()

        return [
            TradePairResponse(
                id=p.id,
                equity_id=p.equity_id,
                open_trade_id=p.open_trade_id,
                close_trade_id=p.close_trade_id,
                quantity_matched=p.quantity_matched,
                realized_pnl=p.realized_pnl,
                holding_period_days=p.holding_period_days,
                calculated_at=p.calculated_at,
                equity=TradeEquity.model_validate(p.equity),
            )
            for p in pairs
        ]

    def calculate_position_size(self, request: PositionSizeRequest) -> PositionSizeResponse:
        """Calculate recommended position size based on risk parameters."""
        risk_amount = request.account_size * (request.risk_percent / Decimal("100"))
        risk_per_share = abs(request.entry_price - request.stop_loss)

        if risk_per_share == 0:
            return PositionSizeResponse(
                shares=0,
                position_value=Decimal("0"),
                risk_amount=risk_amount,
                risk_per_share=Decimal("0"),
                method=request.method,
                notes="Entry price and stop loss are the same - cannot calculate position size",
            )

        shares = int(risk_amount / risk_per_share)
        position_value = Decimal(shares) * request.entry_price

        notes = None
        if position_value > request.account_size * Decimal("0.25"):
            notes = "Warning: Position size exceeds 25% of account"

        return PositionSizeResponse(
            shares=shares,
            position_value=position_value,
            risk_amount=risk_amount,
            risk_per_share=risk_per_share,
            method=request.method,
            notes=notes,
        )

    async def _account_owned(self, user_id: UUID, account_id: int) -> bool:
        """Whether an account exists and belongs to this user."""
        return (
            await self.db.scalar(
                select(func.count(Account.id)).where(
                    Account.id == account_id, Account.user_id == user_id
                )
            )
        ) > 0

    async def _recalculate_pairs(self, user_id: UUID, equity_id: int) -> None:
        """Recalculate all trade pairs for an equity using FIFO method.

        FIFO matching is partitioned by account: a sell in one account only
        matches buys in that same account. The unassigned bucket (account_id
        NULL) is its own partition.
        """
        # Delete existing pairs for this equity
        stmt = select(TradePair).where(
            TradePair.user_id == user_id,
            TradePair.equity_id == equity_id,
        )
        result = await self.db.execute(stmt)
        for pair in result.scalars():
            await self.db.delete(pair)

        # Get all trades for this equity, ordered by execution time. `id` is
        # a secondary sort key so that trades sharing an identical
        # `executed_at` (e.g. same-second imports/backfills) still sort
        # deterministically - timestamp alone is not a unique key, and an
        # unordered tie lets FIFO pairing/cost-basis vary across runs.
        stmt = (
            select(Trade)
            .where(Trade.user_id == user_id, Trade.equity_id == equity_id)
            .order_by(Trade.executed_at, Trade.id)
        )
        result = await self.db.execute(stmt)
        trades = result.scalars().all()

        # FIFO queues keyed by account_id (None = unassigned bucket) so a
        # close only matches opens in the same account.
        # Each entry: (trade_id, remaining_quantity, price, executed_at,
        # open_fee_per_share) - the per-share opening fee rides along so a close
        # can net its matched share of it out of realized P&L.
        long_queues: dict[int | None, list[tuple[int, Decimal, Decimal, datetime, Decimal]]] = {}
        short_queues: dict[int | None, list[tuple[int, Decimal, Decimal, datetime, Decimal]]] = {}

        for trade in trades:
            acct = trade.account_id
            if trade.trade_type == TradeType.BUY:
                # Opening long position
                long_queues.setdefault(acct, []).append(
                    (trade.id, trade.quantity, trade.price, trade.executed_at,
                     _fee_per_share(trade))
                )
            elif trade.trade_type == TradeType.SELL:
                # Closing long position (FIFO within the account)
                queue = long_queues.setdefault(acct, [])
                remaining = trade.quantity
                close_fee_ps = _fee_per_share(trade)
                while remaining > 0 and queue:
                    open_id, open_qty, open_price, open_date, open_fee_ps = queue[0]
                    matched = min(remaining, open_qty)

                    # Net realized P&L = gross price move less the matched share
                    # of BOTH commissions (opening + closing). Fees belong in
                    # realized P&L, not just cost basis - otherwise win-rate and
                    # profit-factor are overstated.
                    pnl = matched * (trade.price - open_price) - matched * (
                        open_fee_ps + close_fee_ps
                    )
                    holding_days = (trade.executed_at - open_date).days

                    self.db.add(
                        TradePair(
                            user_id=user_id,
                            equity_id=equity_id,
                            account_id=acct,
                            open_trade_id=open_id,
                            close_trade_id=trade.id,
                            quantity_matched=matched,
                            realized_pnl=pnl,
                            holding_period_days=holding_days,
                        )
                    )

                    remaining -= matched
                    if matched >= open_qty:
                        queue.pop(0)
                    else:
                        queue[0] = (
                            open_id, open_qty - matched, open_price, open_date,
                            open_fee_ps,
                        )

            elif trade.trade_type == TradeType.SPLIT:
                # A split is a property of the SECURITY, not of one account:
                # it re-denominates every partition holding this equity from a
                # SINGLE row. That is why the row carries no account_id and why
                # this branch loops over all queue keys instead of using
                # `acct`. Deliberately independent of the row's own
                # account_id - if one ever carries an account (a hand-inserted
                # row, or a future revisit of D6), applying it security-wide is
                # still the correct reading.
                #
                # It writes no TradePair: a split realizes nothing.
                ratio = trade.quantity
                for key, queue in long_queues.items():
                    long_queues[key] = split_adjusted_lots(queue, ratio)
                for key, queue in short_queues.items():
                    short_queues[key] = split_adjusted_lots(queue, ratio)

            elif trade.trade_type == TradeType.SHORT:
                # Opening short position
                short_queues.setdefault(acct, []).append(
                    (trade.id, trade.quantity, trade.price, trade.executed_at,
                     _fee_per_share(trade))
                )
            elif trade.trade_type == TradeType.COVER:
                # Closing short position (FIFO within the account)
                queue = short_queues.setdefault(acct, [])
                remaining = trade.quantity
                close_fee_ps = _fee_per_share(trade)
                while remaining > 0 and queue:
                    open_id, open_qty, open_price, open_date, open_fee_ps = queue[0]
                    matched = min(remaining, open_qty)

                    # P&L for short: profit when price goes down, less the
                    # matched share of both commissions (see SELL branch).
                    pnl = matched * (open_price - trade.price) - matched * (
                        open_fee_ps + close_fee_ps
                    )
                    holding_days = (trade.executed_at - open_date).days

                    self.db.add(
                        TradePair(
                            user_id=user_id,
                            equity_id=equity_id,
                            account_id=acct,
                            open_trade_id=open_id,
                            close_trade_id=trade.id,
                            quantity_matched=matched,
                            realized_pnl=pnl,
                            holding_period_days=holding_days,
                        )
                    )

                    remaining -= matched
                    if matched >= open_qty:
                        queue.pop(0)
                    else:
                        queue[0] = (
                            open_id, open_qty - matched, open_price, open_date,
                            open_fee_ps,
                        )

        await self.db.commit()

    async def _get_open_lots(
        self,
        user_id: UUID,
        equity_id: int,
        account_id: int | None,
    ) -> OpenLots:
        """The still-open FIFO lots for one ``(account_id, equity)`` - the same
        walk as :meth:`_recalculate_pairs`, but READ-ONLY and returning the
        leftover queues instead of writing pairs (§3).

        STRICTLY read-only: it never deletes pairs, adds rows, or commits. Two
        spec-pinned differences from the mutating walk:

        * **Deterministic ordering** by ``(executed_at, id)`` - the mutating
          walk orders by ``executed_at`` alone, so same-timestamp trades sort
          unstably; the ``id`` tiebreaker makes the open-lot state reproducible.
        * **Malformed-ledger detection** - the mutating walk silently drops a
          SELL/COVER's unmatched quantity; here that sets
          ``ledger_inconsistent`` so the caller reports the flag instead of a
          basis it can't trust.

        FIFO is partitioned by account, so only this account's trades matter;
        ``account_id=None`` is the unassigned bucket.
        """
        conditions = [
            Trade.user_id == user_id,
            Trade.equity_id == equity_id,
        ]
        account_scope = (
            Trade.account_id.is_(None)
            if account_id is None
            else Trade.account_id == account_id
        )
        # SPLIT rows are security-wide and carry no account, so an
        # `account_id == <int>` filter would silently drop them and this walk
        # would report PRE-split lots to the Schwab basis reconciliation -
        # false drift against the broker. Or-ed in rather than relying on the
        # NULL account, so the walk stays correct if a split row ever carries
        # one. (For account_id=None the or_ is a harmless no-op: a split's
        # NULL account already satisfies the left side.)
        conditions.append(or_(account_scope, Trade.trade_type == TradeType.SPLIT))

        stmt = (
            select(Trade)
            .where(and_(*conditions))
            .order_by(Trade.executed_at, Trade.id)
        )
        result = await self.db.execute(stmt)
        trades = result.scalars().all()

        long_queue: list[OpenLot] = []
        short_queue: list[OpenLot] = []
        ledger_inconsistent = False

        for trade in trades:
            if trade.trade_type == TradeType.BUY:
                long_queue.append(
                    (trade.id, trade.quantity, trade.price, trade.executed_at,
                     _fee_per_share(trade))
                )
            elif trade.trade_type == TradeType.SPLIT:
                # The clone of the mutating walk's split branch, through the
                # one shared helper so the two cannot drift. Both sides, since
                # a split re-denominates a short position exactly as it does a
                # long one.
                long_queue = split_adjusted_lots(long_queue, trade.quantity)
                short_queue = split_adjusted_lots(short_queue, trade.quantity)
            elif trade.trade_type == TradeType.SHORT:
                short_queue.append(
                    (trade.id, trade.quantity, trade.price, trade.executed_at,
                     _fee_per_share(trade))
                )
            elif trade.trade_type in (TradeType.SELL, TradeType.COVER):
                queue = (
                    long_queue if trade.trade_type == TradeType.SELL
                    else short_queue
                )
                remaining = trade.quantity
                while remaining > 0 and queue:
                    open_id, open_qty, open_price, open_date, open_fee = queue[0]
                    matched = min(remaining, open_qty)
                    remaining -= matched
                    if matched >= open_qty:
                        queue.pop(0)
                    else:
                        queue[0] = (
                            open_id, open_qty - matched, open_price, open_date,
                            open_fee,
                        )
                if remaining > 0:
                    # More closed than the queue could match: a ledger the
                    # mutating walk would silently tolerate. Don't trust a basis
                    # computed from it.
                    ledger_inconsistent = True

        return OpenLots(
            long_lots=long_queue,
            short_lots=short_queue,
            ledger_inconsistent=ledger_inconsistent,
        )

    async def _calculate_positions(
        self,
        user_id: UUID,
        equity_id: int | None = None,
        with_quotes: bool = True,
        by_account: bool = False,
    ) -> list[PositionSummary]:
        """Calculate current positions from trades.

        By default positions are aggregated per equity (existing behaviour -
        the portfolio/performance views depend on it). With ``by_account``,
        positions are keyed by (account_id, equity): the same ticker held in
        two accounts becomes two distinct positions, each carrying its account
        context. The unassigned bucket (account_id NULL) is its own position.
        """
        from itertools import groupby

        conditions = [Trade.user_id == user_id]
        if equity_id:
            conditions.append(Trade.equity_id == equity_id)

        options = [selectinload(Trade.equity)]
        order_cols = [Trade.equity_id]
        if by_account:
            options.append(selectinload(Trade.account))
            order_cols.append(Trade.account_id)
        order_cols.append(Trade.executed_at)

        stmt = (
            select(Trade)
            .options(*options)
            .where(and_(*conditions))
            .order_by(*order_cols)
        )
        result = await self.db.execute(stmt)
        trades = result.scalars().all()

        # A split is a property of the SECURITY, not of one account (design
        # doc, Surface 3 "Ordering and scope"): one row re-denominates every
        # account holding that equity, and it carries no account_id of its
        # own. So split rows are pulled out of the per-account grouping and
        # overlaid onto every group for their equity - otherwise a 4:1 split
        # would either manufacture a phantom "unassigned" position or, worse,
        # leave the Roth partition reporting pre-split share counts against
        # post-split FIFO lots.
        splits_by_equity: dict[int, list[Trade]] = {}
        fills: list[Trade] = []
        for t in trades:
            if t.trade_type == TradeType.SPLIT:
                splits_by_equity.setdefault(t.equity_id, []).append(t)
            else:
                fills.append(t)

        def group_key(t: Trade):
            return (t.equity_id, t.account_id) if by_account else (t.equity_id,)

        positions = []
        for _key, group in groupby(fills, key=group_key):
            group_list = list(group)
            if not group_list:
                continue

            equity = group_list[0].equity
            eq_id = group_list[0].equity_id
            account_id = group_list[0].account_id if by_account else None
            account_obj = group_list[0].account if by_account else None

            # first/last are this account's own activity - a security-wide
            # split is not a trade in this account and must not move them.
            first_trade = group_list[0].executed_at
            last_trade = group_list[-1].executed_at

            rows = group_list
            if eq_id in splits_by_equity:
                rows = sorted(
                    group_list + splits_by_equity[eq_id],
                    key=lambda t: (t.executed_at, t.id),
                )
            net_quantity, total_cost = _fold_position(rows)

            # Calculate average cost basis
            avg_cost = abs(total_cost / net_quantity) if net_quantity != 0 else Decimal("0")

            # Get realized P&L (scoped to the account when per-account)
            pnl_conditions = [
                TradePair.user_id == user_id,
                TradePair.equity_id == eq_id,
            ]
            if by_account:
                pnl_conditions.append(
                    TradePair.account_id.is_(None)
                    if account_id is None
                    else TradePair.account_id == account_id
                )
            pnl_result = await self.db.execute(
                select(func.sum(TradePair.realized_pnl)).where(and_(*pnl_conditions))
            )
            realized_pnl = pnl_result.scalar() or Decimal("0")

            # Get current price for unrealized P&L
            current_price = None
            current_value = None
            unrealized_pnl = None
            unrealized_pnl_percent = None

            if net_quantity != 0 and with_quotes:
                quote = await self.equity_service.get_quote(equity.symbol)
                if quote and quote.price:
                    current_price = quote.price
                    current_value = net_quantity * current_price
                    unrealized_pnl = current_value - (net_quantity * avg_cost)
                    if total_cost != 0:
                        unrealized_pnl_percent = (unrealized_pnl / abs(total_cost)) * 100

            positions.append(
                PositionSummary(
                    equity_id=eq_id,
                    equity=TradeEquity.model_validate(equity),
                    account_id=account_id,
                    account=AccountRef.model_validate(account_obj) if account_obj else None,
                    quantity=net_quantity,
                    avg_cost_basis=avg_cost,
                    total_cost=abs(total_cost),
                    current_price=current_price,
                    current_value=current_value,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_percent=unrealized_pnl_percent,
                    realized_pnl=realized_pnl,
                    first_trade_at=first_trade,
                    last_trade_at=last_trade,
                )
            )

        return positions

    def _calculate_metrics(self, pairs: list[TradePair]) -> PerformanceMetrics:
        """Calculate performance metrics from trade pairs."""
        if not pairs:
            return PerformanceMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=Decimal("0"),
                total_realized_pnl=Decimal("0"),
                current_streak=0,
                longest_winning_streak=0,
                longest_losing_streak=0,
            )

        wins = [p for p in pairs if p.realized_pnl > 0]
        losses = [p for p in pairs if p.realized_pnl < 0]

        total_pnl = sum(p.realized_pnl for p in pairs)
        win_rate = Decimal(len(wins)) / Decimal(len(pairs)) if pairs else Decimal("0")

        avg_win = sum(p.realized_pnl for p in wins) / len(wins) if wins else None
        avg_loss = sum(p.realized_pnl for p in losses) / len(losses) if losses else None

        largest_win = max((p.realized_pnl for p in wins), default=None)
        largest_loss = min((p.realized_pnl for p in losses), default=None)

        gross_profit = sum(p.realized_pnl for p in wins)
        gross_loss = abs(sum(p.realized_pnl for p in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        avg_holding = (
            sum(p.holding_period_days for p in pairs) / len(pairs) if pairs else None
        )

        # Calculate streaks
        current_streak = 0
        longest_win_streak = 0
        longest_lose_streak = 0
        current_win = 0
        current_lose = 0

        for p in pairs:
            if p.realized_pnl > 0:
                current_win += 1
                current_lose = 0
                longest_win_streak = max(longest_win_streak, current_win)
            elif p.realized_pnl < 0:
                current_lose += 1
                current_win = 0
                longest_lose_streak = max(longest_lose_streak, current_lose)

        # Current streak (positive = winning, negative = losing)
        if pairs:
            last = pairs[-1]
            if last.realized_pnl > 0:
                current_streak = current_win
            elif last.realized_pnl < 0:
                current_streak = -current_lose

        return PerformanceMetrics(
            total_trades=len(pairs),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=win_rate,
            total_realized_pnl=total_pnl,
            average_win=avg_win,
            average_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            profit_factor=profit_factor,
            average_holding_days=Decimal(str(avg_holding)) if avg_holding else None,
            current_streak=current_streak,
            longest_winning_streak=longest_win_streak,
            longest_losing_streak=longest_lose_streak,
        )

    def _group_by_category(
        self, pairs: list[TradePair], key_func
    ) -> list[PerformanceByCategory]:
        """Group trade pairs by a category and calculate stats."""
        from collections import defaultdict

        groups = defaultdict(list)
        for p in pairs:
            groups[key_func(p)].append(p)

        results = []
        for category, category_pairs in groups.items():
            wins = [p for p in category_pairs if p.realized_pnl > 0]
            total_pnl = sum(p.realized_pnl for p in category_pairs)
            win_rate = Decimal(len(wins)) / Decimal(len(category_pairs)) if category_pairs else Decimal("0")

            results.append(
                PerformanceByCategory(
                    category=category,
                    total_trades=len(category_pairs),
                    realized_pnl=total_pnl,
                    win_rate=win_rate,
                )
            )

        # Sort by P&L descending
        results.sort(key=lambda x: x.realized_pnl, reverse=True)
        return results

    def _trade_to_response(self, trade: Trade) -> TradeResponse:
        """Convert Trade model to TradeResponse schema."""
        return TradeResponse(
            id=trade.id,
            user_id=trade.user_id,
            equity_id=trade.equity_id,
            trade_type=trade.trade_type,
            quantity=trade.quantity,
            price=trade.price,
            fees=trade.fees,
            executed_at=trade.executed_at,
            notes=trade.notes,
            watchlist_item_id=trade.watchlist_item_id,
            account_id=trade.account_id,
            account=AccountRef.model_validate(trade.account) if trade.account else None,
            equity=TradeEquity.model_validate(trade.equity),
            total_value=trade.total_value,
            total_cost=trade.total_cost,
            source=trade.source,
            is_synthetic=trade.is_synthetic,
            basis_is_estimated=trade.basis_is_estimated,
            source_import_run_id=trade.source_import_run_id,
            created_at=trade.created_at,
            updated_at=trade.updated_at,
        )
