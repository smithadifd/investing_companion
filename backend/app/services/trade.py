"""Trade service - business logic for trade operations and P&L calculation."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.equity import Equity
from app.db.models.trade import Trade, TradePair, TradeType
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
)
from app.services.equity import EquityService


class TradeService:
    """Service for trade-related operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.equity_service = EquityService(db)

    async def list_trades(
        self,
        user_id: UUID,
        equity_id: Optional[int] = None,
        trade_type: Optional[TradeType] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[TradeResponse], int]:
        """List trades with optional filters."""
        conditions = [Trade.user_id == user_id]

        if equity_id:
            conditions.append(Trade.equity_id == equity_id)
        if trade_type:
            conditions.append(Trade.trade_type == trade_type)
        if start_date:
            conditions.append(Trade.executed_at >= start_date)
        if end_date:
            conditions.append(Trade.executed_at <= end_date)

        # Count total
        count_stmt = select(func.count(Trade.id)).where(and_(*conditions))
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        # Fetch trades
        stmt = (
            select(Trade)
            .options(selectinload(Trade.equity))
            .where(and_(*conditions))
            .order_by(Trade.executed_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        trades = result.scalars().all()

        return [self._trade_to_response(t) for t in trades], total

    async def get_trade(self, trade_id: int, user_id: UUID) -> Optional[TradeResponse]:
        """Get a single trade by ID."""
        stmt = (
            select(Trade)
            .options(selectinload(Trade.equity))
            .where(Trade.id == trade_id, Trade.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        trade = result.scalar_one_or_none()

        if not trade:
            return None

        return self._trade_to_response(trade)

    async def create_trade(self, user_id: UUID, data: TradeCreate) -> Optional[TradeResponse]:
        """Create a new trade and recalculate P&L pairs."""
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
        )

        self.db.add(trade)
        await self.db.commit()
        await self.db.refresh(trade)

        # Recalculate P&L pairs for this equity
        await self._recalculate_pairs(user_id, equity.id)

        # Reload with equity
        stmt = (
            select(Trade)
            .options(selectinload(Trade.equity))
            .where(Trade.id == trade.id)
        )
        result = await self.db.execute(stmt)
        trade = result.scalar_one()

        return self._trade_to_response(trade)

    async def update_trade(
        self, trade_id: int, user_id: UUID, data: TradeUpdate
    ) -> Optional[TradeResponse]:
        """Update a trade and recalculate P&L pairs."""
        stmt = (
            select(Trade)
            .options(selectinload(Trade.equity))
            .where(Trade.id == trade_id, Trade.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        trade = result.scalar_one_or_none()

        if not trade:
            return None

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

        await self.db.commit()
        await self.db.refresh(trade)

        # Recalculate P&L pairs for this equity
        await self._recalculate_pairs(user_id, trade.equity_id)

        return self._trade_to_response(trade)

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

    async def get_position(self, user_id: UUID, equity_id: int) -> Optional[PositionSummary]:
        """Get current position for a single equity."""
        positions = await self._calculate_positions(user_id, equity_id=equity_id)
        return positions[0] if positions else None

    async def get_portfolio(self, user_id: UUID) -> PortfolioSummary:
        """Get portfolio summary with all positions."""
        positions = await self._calculate_positions(user_id)

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
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
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
        equity_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[TradePairResponse]:
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

    async def _recalculate_pairs(self, user_id: UUID, equity_id: int) -> None:
        """Recalculate all trade pairs for an equity using FIFO method."""
        # Delete existing pairs for this equity
        stmt = select(TradePair).where(
            TradePair.user_id == user_id,
            TradePair.equity_id == equity_id,
        )
        result = await self.db.execute(stmt)
        for pair in result.scalars():
            await self.db.delete(pair)

        # Get all trades for this equity, ordered by execution time
        stmt = (
            select(Trade)
            .where(Trade.user_id == user_id, Trade.equity_id == equity_id)
            .order_by(Trade.executed_at)
        )
        result = await self.db.execute(stmt)
        trades = result.scalars().all()

        # Track open positions (FIFO queue)
        # For long positions: list of (trade_id, remaining_quantity, price)
        # For short positions: similar structure
        long_queue: List[Tuple[int, Decimal, Decimal, datetime]] = []
        short_queue: List[Tuple[int, Decimal, Decimal, datetime]] = []

        for trade in trades:
            if trade.trade_type == TradeType.BUY:
                # Opening long position
                long_queue.append((trade.id, trade.quantity, trade.price, trade.executed_at))
            elif trade.trade_type == TradeType.SELL:
                # Closing long position (FIFO)
                remaining = trade.quantity
                while remaining > 0 and long_queue:
                    open_id, open_qty, open_price, open_date = long_queue[0]
                    matched = min(remaining, open_qty)

                    # Calculate P&L for this match
                    pnl = matched * (trade.price - open_price)
                    holding_days = (trade.executed_at - open_date).days

                    pair = TradePair(
                        user_id=user_id,
                        equity_id=equity_id,
                        open_trade_id=open_id,
                        close_trade_id=trade.id,
                        quantity_matched=matched,
                        realized_pnl=pnl,
                        holding_period_days=holding_days,
                    )
                    self.db.add(pair)

                    remaining -= matched
                    if matched >= open_qty:
                        long_queue.pop(0)
                    else:
                        long_queue[0] = (open_id, open_qty - matched, open_price, open_date)

            elif trade.trade_type == TradeType.SHORT:
                # Opening short position
                short_queue.append((trade.id, trade.quantity, trade.price, trade.executed_at))
            elif trade.trade_type == TradeType.COVER:
                # Closing short position (FIFO)
                remaining = trade.quantity
                while remaining > 0 and short_queue:
                    open_id, open_qty, open_price, open_date = short_queue[0]
                    matched = min(remaining, open_qty)

                    # P&L for short: profit when price goes down
                    pnl = matched * (open_price - trade.price)
                    holding_days = (trade.executed_at - open_date).days

                    pair = TradePair(
                        user_id=user_id,
                        equity_id=equity_id,
                        open_trade_id=open_id,
                        close_trade_id=trade.id,
                        quantity_matched=matched,
                        realized_pnl=pnl,
                        holding_period_days=holding_days,
                    )
                    self.db.add(pair)

                    remaining -= matched
                    if matched >= open_qty:
                        short_queue.pop(0)
                    else:
                        short_queue[0] = (open_id, open_qty - matched, open_price, open_date)

        await self.db.commit()

    async def _calculate_positions(
        self, user_id: UUID, equity_id: Optional[int] = None
    ) -> List[PositionSummary]:
        """Calculate current positions from trades."""
        conditions = [Trade.user_id == user_id]
        if equity_id:
            conditions.append(Trade.equity_id == equity_id)

        # Get all trades grouped by equity
        stmt = (
            select(Trade)
            .options(selectinload(Trade.equity))
            .where(and_(*conditions))
            .order_by(Trade.equity_id, Trade.executed_at)
        )
        result = await self.db.execute(stmt)
        trades = result.scalars().all()

        # Group trades by equity
        from itertools import groupby
        from operator import attrgetter

        positions = []
        for eq_id, equity_trades in groupby(trades, key=attrgetter("equity_id")):
            equity_trades_list = list(equity_trades)
            if not equity_trades_list:
                continue

            equity = equity_trades_list[0].equity

            # Calculate net position
            net_quantity = Decimal("0")
            total_cost = Decimal("0")
            first_trade = equity_trades_list[0].executed_at
            last_trade = equity_trades_list[-1].executed_at

            for t in equity_trades_list:
                if t.trade_type in (TradeType.BUY, TradeType.COVER):
                    net_quantity += t.quantity
                    total_cost += t.quantity * t.price + t.fees
                else:  # SELL or SHORT
                    net_quantity -= t.quantity
                    total_cost -= t.quantity * t.price - t.fees

            if net_quantity == 0 and total_cost == 0:
                # Position closed, but include for history
                pass

            # Calculate average cost basis
            avg_cost = abs(total_cost / net_quantity) if net_quantity != 0 else Decimal("0")

            # Get realized P&L
            pnl_stmt = select(func.sum(TradePair.realized_pnl)).where(
                TradePair.user_id == user_id,
                TradePair.equity_id == eq_id,
            )
            pnl_result = await self.db.execute(pnl_stmt)
            realized_pnl = pnl_result.scalar() or Decimal("0")

            # Get current price for unrealized P&L
            current_price = None
            current_value = None
            unrealized_pnl = None
            unrealized_pnl_percent = None

            if net_quantity != 0:
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

    def _calculate_metrics(self, pairs: List[TradePair]) -> PerformanceMetrics:
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
        self, pairs: List[TradePair], key_func
    ) -> List[PerformanceByCategory]:
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
            equity=TradeEquity.model_validate(trade.equity),
            total_value=trade.total_value,
            total_cost=trade.total_cost,
            created_at=trade.created_at,
            updated_at=trade.updated_at,
        )
