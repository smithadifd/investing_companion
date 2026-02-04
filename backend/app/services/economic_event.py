"""Economic event service - business logic for calendar and event operations."""

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.economic_event import EconomicEvent, EventSource, EventType
from app.db.models.equity import Equity
from app.db.models.watchlist import Watchlist, WatchlistItem
from app.schemas.economic_event import (
    CalendarDay,
    CalendarMonth,
    EarningsInfo,
    EconomicEventCreate,
    EconomicEventResponse,
    EconomicEventUpdate,
    EquityBrief,
    EquityCalendarInfo,
    EventFilters,
    EventImportance,
    EventStats,
    EventType as EventTypeSchema,
    EQUITY_EVENT_TYPES,
    MACRO_EVENT_TYPES,
    UpcomingEventsResponse,
)
from app.services.data_providers.yahoo import YahooFinanceProvider

logger = logging.getLogger(__name__)


class EconomicEventService:
    """Service for economic event and calendar operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.yahoo = YahooFinanceProvider()

    # -------------------------------------------------------------------------
    # CRUD Operations
    # -------------------------------------------------------------------------

    async def list_events(
        self,
        filters: Optional[EventFilters] = None,
        user_id: Optional[uuid.UUID] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[EconomicEventResponse]:
        """List events with optional filtering."""
        stmt = select(EconomicEvent)

        # Apply filters
        if filters:
            if filters.start_date:
                stmt = stmt.where(EconomicEvent.event_date >= filters.start_date)
            if filters.end_date:
                stmt = stmt.where(EconomicEvent.event_date <= filters.end_date)
            if filters.event_types:
                type_values = [t.value for t in filters.event_types]
                stmt = stmt.where(EconomicEvent.event_type.in_(type_values))
            if filters.equity_id:
                stmt = stmt.where(EconomicEvent.equity_id == filters.equity_id)
            if filters.importance:
                stmt = stmt.where(EconomicEvent.importance == filters.importance.value)
            if not filters.include_past:
                stmt = stmt.where(EconomicEvent.event_date >= date.today())

            # Filter by watchlist
            if filters.watchlist_id or filters.watchlist_only:
                watchlist_equity_ids = await self._get_watchlist_equity_ids(
                    user_id, filters.watchlist_id
                )
                if watchlist_equity_ids:
                    if filters.watchlist_only:
                        # Only show equity events for watchlist items (no macro)
                        stmt = stmt.where(
                            EconomicEvent.equity_id.in_(watchlist_equity_ids)
                        )
                    else:
                        # Show macro events + equity events for watchlist items
                        stmt = stmt.where(
                            or_(
                                EconomicEvent.equity_id.in_(watchlist_equity_ids),
                                EconomicEvent.equity_id.is_(None),  # Macro events
                            )
                        )
                elif filters.watchlist_only:
                    # No watchlist items, show nothing (no macro, no equities)
                    stmt = stmt.where(EconomicEvent.equity_id == -1)  # Impossible condition

        # Custom events are user-specific
        stmt = stmt.where(
            or_(
                EconomicEvent.user_id.is_(None),  # System/seeded events
                EconomicEvent.user_id == user_id,  # User's custom events
            )
        )

        stmt = stmt.order_by(EconomicEvent.event_date, EconomicEvent.event_time)
        stmt = stmt.limit(limit).offset(offset)

        result = await self.db.execute(stmt)
        events = result.scalars().all()

        return [await self._to_response(e) for e in events]

    async def get_event(
        self, event_id: uuid.UUID, user_id: Optional[uuid.UUID] = None
    ) -> Optional[EconomicEventResponse]:
        """Get a single event by ID."""
        stmt = select(EconomicEvent).where(EconomicEvent.id == event_id)
        result = await self.db.execute(stmt)
        event = result.scalar_one_or_none()

        if event:
            # Check access for custom events
            if event.user_id and event.user_id != user_id:
                return None
            return await self._to_response(event)
        return None

    async def create_event(
        self,
        data: EconomicEventCreate,
        user_id: uuid.UUID,
    ) -> EconomicEventResponse:
        """Create a custom event."""
        # Look up equity if symbol provided
        equity_id = None
        if data.equity_symbol:
            equity = await self._get_or_create_equity(data.equity_symbol)
            if equity:
                equity_id = equity.id

        event = EconomicEvent(
            event_type=data.event_type.value,
            equity_id=equity_id,
            user_id=user_id,
            event_date=data.event_date,
            event_time=data.event_time,
            all_day=data.all_day,
            title=data.title,
            description=data.description,
            actual_value=data.actual_value,
            forecast_value=data.forecast_value,
            previous_value=data.previous_value,
            importance=data.importance.value,
            source=EventSource.MANUAL.value,
            is_confirmed=data.is_confirmed,
        )

        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)

        return await self._to_response(event)

    async def update_event(
        self,
        event_id: uuid.UUID,
        data: EconomicEventUpdate,
        user_id: uuid.UUID,
    ) -> Optional[EconomicEventResponse]:
        """Update an event (only custom events can be updated)."""
        stmt = select(EconomicEvent).where(EconomicEvent.id == event_id)
        result = await self.db.execute(stmt)
        event = result.scalar_one_or_none()

        if not event:
            return None

        # Only allow updating user's own custom events
        if event.user_id != user_id:
            return None

        # Update fields
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if field == "importance" and value:
                value = value.value
            setattr(event, field, value)

        await self.db.commit()
        await self.db.refresh(event)

        return await self._to_response(event)

    async def delete_event(
        self, event_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        """Delete a custom event."""
        stmt = select(EconomicEvent).where(
            EconomicEvent.id == event_id,
            EconomicEvent.user_id == user_id,  # Only user's custom events
        )
        result = await self.db.execute(stmt)
        event = result.scalar_one_or_none()

        if not event:
            return False

        await self.db.delete(event)
        await self.db.commit()
        return True

    async def delete_events_for_symbol(self, symbol: str) -> int:
        """Delete all events for a specific equity symbol.

        This removes all auto-fetched events (earnings, dividends, etc.)
        for an equity. Used when a user wants to stop tracking an equity.

        Returns the number of events deleted.
        """
        equity = await self._get_equity_by_symbol(symbol)
        if not equity:
            return 0

        # Only delete system events (source != 'manual'), not user custom events
        stmt = delete(EconomicEvent).where(
            EconomicEvent.equity_id == equity.id,
            EconomicEvent.source != 'manual',  # Preserve user's custom events
        )
        result = await self.db.execute(stmt)
        await self.db.commit()

        return result.rowcount

    # -------------------------------------------------------------------------
    # Calendar Views
    # -------------------------------------------------------------------------

    async def get_calendar_month(
        self,
        year: int,
        month: int,
        user_id: Optional[uuid.UUID] = None,
        filters: Optional[EventFilters] = None,
    ) -> CalendarMonth:
        """Get events organized by day for a month."""
        # Calculate date range
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        # Get events for the month
        if filters is None:
            filters = EventFilters()
        filters.start_date = start_date
        filters.end_date = end_date
        filters.include_past = True  # Show all days in month

        events = await self.list_events(filters, user_id)

        # Group by day
        events_by_day: dict[date, list[EconomicEventResponse]] = {}
        for event in events:
            if event.event_date not in events_by_day:
                events_by_day[event.event_date] = []
            events_by_day[event.event_date].append(event)

        # Build calendar days
        days = []
        current = start_date
        while current <= end_date:
            day_events = events_by_day.get(current, [])
            has_earnings = any(
                e.event_type == EventTypeSchema.EARNINGS for e in day_events
            )
            has_macro = any(
                e.event_type.value in [t.value for t in MACRO_EVENT_TYPES]
                for e in day_events
            )
            days.append(
                CalendarDay(
                    date=current,
                    events=day_events,
                    has_earnings=has_earnings,
                    has_macro=has_macro,
                    event_count=len(day_events),
                )
            )
            current += timedelta(days=1)

        return CalendarMonth(
            year=year,
            month=month,
            days=days,
            total_events=len(events),
        )

    async def get_upcoming_events(
        self,
        days_ahead: int = 7,
        user_id: Optional[uuid.UUID] = None,
        filters: Optional[EventFilters] = None,
        limit: int = 20,
    ) -> UpcomingEventsResponse:
        """Get upcoming events for the next N days."""
        if filters is None:
            filters = EventFilters()
        filters.start_date = date.today()
        filters.end_date = date.today() + timedelta(days=days_ahead)
        filters.include_past = False

        events = await self.list_events(filters, user_id, limit=limit)

        return UpcomingEventsResponse(
            events=events,
            total=len(events),
            days_ahead=days_ahead,
        )

    async def get_events_for_equity(
        self,
        equity_id: int,
        include_past: bool = False,
        limit: int = 10,
    ) -> List[EconomicEventResponse]:
        """Get events for a specific equity."""
        filters = EventFilters(
            equity_id=equity_id,
            include_past=include_past,
        )
        return await self.list_events(filters, limit=limit)

    async def get_events_for_symbol(
        self,
        symbol: str,
        include_past: bool = False,
        limit: int = 10,
    ) -> List[EconomicEventResponse]:
        """Get events for a specific equity symbol."""
        equity = await self._get_equity_by_symbol(symbol)
        if not equity:
            return []
        return await self.get_events_for_equity(equity.id, include_past, limit)

    async def get_watchlist_events(
        self,
        user_id: uuid.UUID,
        watchlist_id: Optional[int] = None,
        days_ahead: int = 14,
    ) -> List[EconomicEventResponse]:
        """Get upcoming events for watchlist equities."""
        filters = EventFilters(
            watchlist_id=watchlist_id,
            watchlist_only=True,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=days_ahead),
        )
        # Only equity events, no macro
        filters.event_types = EQUITY_EVENT_TYPES
        return await self.list_events(filters, user_id)

    # -------------------------------------------------------------------------
    # Yahoo Finance Integration
    # -------------------------------------------------------------------------

    async def refresh_equity_events(
        self, symbol: str, equity_id: Optional[int] = None
    ) -> List[EconomicEventResponse]:
        """Refresh events for an equity from Yahoo Finance.

        Creates or updates earnings and dividend events.
        """
        # Get equity
        equity = await self._get_equity_by_symbol(symbol)
        if not equity:
            equity = await self._get_or_create_equity(symbol)
        if not equity:
            return []

        # Fetch from Yahoo
        calendar_info = await self.yahoo.get_calendar(symbol)
        if not calendar_info:
            return []

        created_events = []

        # Process earnings
        if calendar_info.earnings and calendar_info.earnings.earnings_date:
            event = await self._upsert_equity_event(
                equity_id=equity.id,
                event_type=EventType.EARNINGS.value,
                event_date=calendar_info.earnings.earnings_date,
                title=f"{symbol} Earnings",
                importance=EventImportance.HIGH.value,
                is_confirmed=calendar_info.earnings.is_confirmed,
            )
            if event:
                created_events.append(await self._to_response(event))

        # Process ex-dividend
        if calendar_info.dividend and calendar_info.dividend.ex_dividend_date:
            # Only add if in the future
            if calendar_info.dividend.ex_dividend_date >= date.today():
                event = await self._upsert_equity_event(
                    equity_id=equity.id,
                    event_type=EventType.EX_DIVIDEND.value,
                    event_date=calendar_info.dividend.ex_dividend_date,
                    title=f"{symbol} Ex-Dividend",
                    importance=EventImportance.MEDIUM.value,
                    actual_value=calendar_info.dividend.dividend_amount,
                )
                if event:
                    created_events.append(await self._to_response(event))

        # Process dividend payment date
        if calendar_info.dividend and calendar_info.dividend.dividend_date:
            if calendar_info.dividend.dividend_date >= date.today():
                event = await self._upsert_equity_event(
                    equity_id=equity.id,
                    event_type=EventType.DIVIDEND_PAY.value,
                    event_date=calendar_info.dividend.dividend_date,
                    title=f"{symbol} Dividend Payment",
                    importance=EventImportance.LOW.value,
                    actual_value=calendar_info.dividend.dividend_amount,
                )
                if event:
                    created_events.append(await self._to_response(event))

        return created_events

    async def refresh_watchlist_events(
        self, user_id: uuid.UUID, watchlist_id: Optional[int] = None
    ) -> int:
        """Refresh events for all equities in user's watchlists.

        Returns the number of events created/updated.
        """
        equity_ids = await self._get_watchlist_equity_ids(user_id, watchlist_id)

        if not equity_ids:
            return 0

        # Get symbols for the equity IDs
        stmt = select(Equity).where(Equity.id.in_(equity_ids))
        result = await self.db.execute(stmt)
        equities = result.scalars().all()

        count = 0
        for equity in equities:
            try:
                events = await self.refresh_equity_events(equity.symbol, equity.id)
                count += len(events)
            except Exception as e:
                logger.warning(f"Failed to refresh events for {equity.symbol}: {e}")

        return count

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    async def get_stats(
        self, user_id: Optional[uuid.UUID] = None
    ) -> EventStats:
        """Get event statistics."""
        today = date.today()
        week_end = today + timedelta(days=7)

        # Total events
        total_stmt = select(func.count(EconomicEvent.id))
        total_result = await self.db.execute(total_stmt)
        total = total_result.scalar() or 0

        # Earnings this week
        earnings_stmt = select(func.count(EconomicEvent.id)).where(
            EconomicEvent.event_type == EventType.EARNINGS.value,
            EconomicEvent.event_date >= today,
            EconomicEvent.event_date <= week_end,
        )
        earnings_result = await self.db.execute(earnings_stmt)
        earnings_this_week = earnings_result.scalar() or 0

        # Macro events this week
        macro_types = [t.value for t in MACRO_EVENT_TYPES]
        macro_stmt = select(func.count(EconomicEvent.id)).where(
            EconomicEvent.event_type.in_(macro_types),
            EconomicEvent.event_date >= today,
            EconomicEvent.event_date <= week_end,
        )
        macro_result = await self.db.execute(macro_stmt)
        macro_this_week = macro_result.scalar() or 0

        # Next FOMC
        fomc_stmt = (
            select(EconomicEvent.event_date)
            .where(
                EconomicEvent.event_type == EventType.FOMC.value,
                EconomicEvent.event_date >= today,
            )
            .order_by(EconomicEvent.event_date)
            .limit(1)
        )
        fomc_result = await self.db.execute(fomc_stmt)
        next_fomc = fomc_result.scalar_one_or_none()

        # Watchlist earnings upcoming
        watchlist_earnings = 0
        if user_id:
            equity_ids = await self._get_watchlist_equity_ids(user_id)
            if equity_ids:
                watch_stmt = select(func.count(EconomicEvent.id)).where(
                    EconomicEvent.event_type == EventType.EARNINGS.value,
                    EconomicEvent.equity_id.in_(equity_ids),
                    EconomicEvent.event_date >= today,
                    EconomicEvent.event_date <= week_end,
                )
                watch_result = await self.db.execute(watch_stmt)
                watchlist_earnings = watch_result.scalar() or 0

        return EventStats(
            total_events=total,
            earnings_this_week=earnings_this_week,
            macro_events_this_week=macro_this_week,
            next_fomc_date=next_fomc,
            watchlist_earnings_upcoming=watchlist_earnings,
        )

    # -------------------------------------------------------------------------
    # Private Helpers
    # -------------------------------------------------------------------------

    async def _to_response(self, event: EconomicEvent) -> EconomicEventResponse:
        """Convert model to response with enriched data."""
        equity_brief = None
        if event.equity:
            equity_brief = EquityBrief(
                id=event.equity.id,
                symbol=event.equity.symbol,
                name=event.equity.name,
            )

        return EconomicEventResponse(
            id=event.id,
            event_type=EventTypeSchema(event.event_type),
            equity_id=event.equity_id,
            user_id=event.user_id,
            event_date=event.event_date,
            event_time=event.event_time,
            all_day=event.all_day,
            title=event.title,
            description=event.description,
            actual_value=event.actual_value,
            forecast_value=event.forecast_value,
            previous_value=event.previous_value,
            importance=EventImportance(event.importance),
            source=EventSource(event.source),
            is_confirmed=event.is_confirmed,
            recurrence_key=event.recurrence_key,
            created_at=event.created_at,
            updated_at=event.updated_at,
            equity=equity_brief,
        )

    async def _get_watchlist_equity_ids(
        self, user_id: Optional[uuid.UUID], watchlist_id: Optional[int] = None
    ) -> List[int]:
        """Get equity IDs from user's watchlist(s)."""
        if not user_id:
            return []

        stmt = (
            select(WatchlistItem.equity_id)
            .join(Watchlist)
            .where(Watchlist.user_id == user_id)
        )
        if watchlist_id:
            stmt = stmt.where(Watchlist.id == watchlist_id)

        result = await self.db.execute(stmt)
        return [row[0] for row in result.all() if row[0] is not None]

    async def _get_equity_by_symbol(self, symbol: str) -> Optional[Equity]:
        """Get equity by symbol."""
        stmt = select(Equity).where(Equity.symbol == symbol.upper())
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_create_equity(self, symbol: str) -> Optional[Equity]:
        """Get or create equity by symbol."""
        equity = await self._get_equity_by_symbol(symbol)
        if equity:
            return equity

        # Fetch info and create
        info = await self.yahoo.get_info(symbol)
        if not info or not info.get("symbol"):
            return None

        equity = Equity(
            symbol=info["symbol"].upper(),
            name=info.get("longName") or info.get("shortName") or symbol,
            exchange=info.get("exchange"),
            asset_type=(info.get("quoteType") or "stock").lower(),
            sector=info.get("sector"),
            industry=info.get("industry"),
        )
        self.db.add(equity)
        await self.db.commit()
        await self.db.refresh(equity)
        return equity

    async def _upsert_equity_event(
        self,
        equity_id: int,
        event_type: str,
        event_date: date,
        title: str,
        importance: str = "medium",
        is_confirmed: bool = True,
        actual_value: Optional[float] = None,
    ) -> Optional[EconomicEvent]:
        """Create or update an equity event (upsert by unique constraint)."""
        # Check if exists
        stmt = select(EconomicEvent).where(
            EconomicEvent.equity_id == equity_id,
            EconomicEvent.event_type == event_type,
            EconomicEvent.event_date == event_date,
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update if changed
            existing.title = title
            existing.importance = importance
            existing.is_confirmed = is_confirmed
            existing.source = EventSource.YAHOO.value
            if actual_value is not None:
                existing.actual_value = actual_value
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        else:
            # Create new
            event = EconomicEvent(
                event_type=event_type,
                equity_id=equity_id,
                event_date=event_date,
                title=title,
                importance=importance,
                source=EventSource.YAHOO.value,
                is_confirmed=is_confirmed,
                actual_value=actual_value,
            )
            self.db.add(event)
            await self.db.commit()
            await self.db.refresh(event)
            return event
