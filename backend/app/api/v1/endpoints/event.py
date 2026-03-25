"""Economic event API endpoints."""

from datetime import date
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_current_user_optional, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import DataResponse, ResponseMeta
from app.schemas.economic_event import (
    CalendarMonth,
    EconomicEventCreate,
    EconomicEventResponse,
    EconomicEventUpdate,
    EventFilters,
    EventImportance,
    EventStats,
    EventType,
    UpcomingEventsResponse,
)
from app.services.economic_event import EconomicEventService

router = APIRouter()


def get_event_service(db: AsyncSession = Depends(get_db)) -> EconomicEventService:
    """Dependency to get event service instance."""
    return EconomicEventService(db)


# -----------------------------------------------------------------------------
# List and Filter Events
# -----------------------------------------------------------------------------


@router.get("", response_model=DataResponse[List[EconomicEventResponse]])
async def list_events(
    start_date: Optional[date] = Query(None, description="Filter events from this date"),
    end_date: Optional[date] = Query(None, description="Filter events until this date"),
    event_types: Optional[List[EventType]] = Query(
        None, description="Filter by event types"
    ),
    equity_symbol: Optional[str] = Query(None, description="Filter by equity symbol"),
    watchlist_id: Optional[int] = Query(None, description="Filter by watchlist"),
    watchlist_only: bool = Query(False, description="Only show watchlist equity events"),
    importance: Optional[EventImportance] = Query(None, description="Filter by importance"),
    include_past: bool = Query(False, description="Include past events"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    service: EconomicEventService = Depends(get_event_service),
) -> DataResponse[List[EconomicEventResponse]]:
    """
    List economic events with filtering.

    Filters:
    - **start_date/end_date**: Date range
    - **event_types**: Filter by type (earnings, fomc, cpi, etc.)
    - **equity_symbol**: Filter by specific equity
    - **watchlist_id**: Filter by watchlist equities
    - **watchlist_only**: Only show equity events (no macro)
    - **importance**: Filter by importance level
    - **include_past**: Include events before today
    """
    filters = EventFilters(
        start_date=start_date,
        end_date=end_date,
        event_types=event_types,
        equity_symbol=equity_symbol,
        watchlist_id=watchlist_id,
        watchlist_only=watchlist_only,
        importance=importance,
        include_past=include_past,
    )

    events = await service.list_events(
        filters=filters,
        user_id=current_user.id if current_user else None,
        limit=limit,
        offset=offset,
    )

    return DataResponse(data=events, meta=ResponseMeta.now())


@router.get("/upcoming", response_model=DataResponse[UpcomingEventsResponse])
async def get_upcoming_events(
    days: int = Query(7, ge=1, le=90, description="Days ahead to look"),
    event_types: Optional[List[EventType]] = Query(None, description="Filter by types"),
    watchlist_only: bool = Query(False, description="Only watchlist equities"),
    limit: int = Query(20, ge=1, le=100, description="Max events"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    service: EconomicEventService = Depends(get_event_service),
) -> DataResponse[UpcomingEventsResponse]:
    """
    Get upcoming events for the next N days.

    Great for dashboard widgets and quick views.
    """
    filters = EventFilters(
        event_types=event_types,
        watchlist_only=watchlist_only,
    )

    result = await service.get_upcoming_events(
        days_ahead=days,
        user_id=current_user.id if current_user else None,
        filters=filters,
        limit=limit,
    )

    return DataResponse(data=result, meta=ResponseMeta.now())


@router.get("/calendar/{year}/{month}", response_model=DataResponse[CalendarMonth])
async def get_calendar_month(
    year: int = Path(..., ge=2020, le=2100, description="Calendar year"),
    month: int = Path(..., ge=1, le=12, description="Calendar month (1-12)"),
    event_types: Optional[List[EventType]] = Query(None, description="Filter by types"),
    watchlist_only: bool = Query(False, description="Only watchlist equities"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    service: EconomicEventService = Depends(get_event_service),
) -> DataResponse[CalendarMonth]:
    """
    Get calendar data for a specific month.

    Returns events grouped by day for calendar display.
    """
    filters = EventFilters(
        event_types=event_types,
        watchlist_only=watchlist_only,
        include_past=True,  # Show full month
    )

    result = await service.get_calendar_month(
        year=year,
        month=month,
        user_id=current_user.id if current_user else None,
        filters=filters,
    )

    return DataResponse(data=result, meta=ResponseMeta.now())


@router.get("/watchlist", response_model=DataResponse[List[EconomicEventResponse]])
async def get_watchlist_events(
    watchlist_id: Optional[int] = Query(None, description="Specific watchlist ID"),
    days: int = Query(14, ge=1, le=90, description="Days ahead"),
    current_user: User = Depends(get_current_user),
    service: EconomicEventService = Depends(get_event_service),
) -> DataResponse[List[EconomicEventResponse]]:
    """
    Get upcoming events for watchlist equities.

    Requires authentication. Shows earnings, dividends, and splits
    for equities in the user's watchlist(s).
    """
    events = await service.get_watchlist_events(
        user_id=current_user.id,
        watchlist_id=watchlist_id,
        days_ahead=days,
    )

    return DataResponse(data=events, meta=ResponseMeta.now())


@router.get("/stats", response_model=DataResponse[EventStats])
async def get_event_stats(
    current_user: Optional[User] = Depends(get_current_user_optional),
    service: EconomicEventService = Depends(get_event_service),
) -> DataResponse[EventStats]:
    """
    Get event statistics.

    Returns counts for earnings, macro events, and next FOMC date.
    """
    stats = await service.get_stats(
        user_id=current_user.id if current_user else None
    )
    return DataResponse(data=stats, meta=ResponseMeta.now())


# -----------------------------------------------------------------------------
# Single Event Operations
# -----------------------------------------------------------------------------


@router.get("/{event_id}", response_model=DataResponse[EconomicEventResponse])
async def get_event(
    event_id: UUID,
    current_user: Optional[User] = Depends(get_current_user_optional),
    service: EconomicEventService = Depends(get_event_service),
) -> DataResponse[EconomicEventResponse]:
    """Get a single event by ID."""
    event = await service.get_event(
        event_id=event_id,
        user_id=current_user.id if current_user else None,
    )
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    return DataResponse(data=event, meta=ResponseMeta.now())


@router.post("", response_model=DataResponse[EconomicEventResponse], status_code=status.HTTP_201_CREATED)
async def create_event(
    data: EconomicEventCreate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: EconomicEventService = Depends(get_event_service),
) -> DataResponse[EconomicEventResponse]:
    """
    Create a custom event.

    Custom events are user-specific and can be edited/deleted.
    Use for personal reminders, portfolio reviews, etc.
    """
    event = await service.create_event(data=data, user_id=current_user.id)
    return DataResponse(data=event, meta=ResponseMeta.now())


@router.put("/{event_id}", response_model=DataResponse[EconomicEventResponse])
async def update_event(
    event_id: UUID,
    data: EconomicEventUpdate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: EconomicEventService = Depends(get_event_service),
) -> DataResponse[EconomicEventResponse]:
    """
    Update an event.

    Only custom events owned by the user can be updated.
    System events (earnings from Yahoo, seeded macro events) cannot be modified.
    """
    event = await service.update_event(
        event_id=event_id,
        data=data,
        user_id=current_user.id,
    )
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found or cannot be modified",
        )
    return DataResponse(data=event, meta=ResponseMeta.now())


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: UUID,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: EconomicEventService = Depends(get_event_service),
) -> None:
    """
    Delete a custom event.

    Only custom events owned by the user can be deleted.
    """
    deleted = await service.delete_event(event_id=event_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found or cannot be deleted",
        )


@router.delete("/equity/{symbol}", response_model=DataResponse[dict])
async def delete_equity_events(
    symbol: str,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: EconomicEventService = Depends(get_event_service),
) -> DataResponse[dict]:
    """
    Delete all auto-fetched events for a specific equity.

    This removes earnings, dividend, and other system-generated events
    for the equity. Use this to "untrack" an equity's events.
    User-created custom events are preserved.
    """
    count = await service.delete_events_for_symbol(symbol.upper())
    return DataResponse(
        data={"symbol": symbol.upper(), "events_deleted": count},
        meta=ResponseMeta.now(),
    )


# -----------------------------------------------------------------------------
# Refresh Events from Data Sources
# -----------------------------------------------------------------------------


@router.post("/refresh/{symbol}", response_model=DataResponse[List[EconomicEventResponse]])
async def refresh_equity_events(
    symbol: str,
    current_user: User = Depends(get_current_user),
    service: EconomicEventService = Depends(get_event_service),
) -> DataResponse[List[EconomicEventResponse]]:
    """
    Refresh events for a specific equity from Yahoo Finance.

    Fetches and updates earnings dates, ex-dividend dates, etc.
    """
    events = await service.refresh_equity_events(symbol.upper())
    return DataResponse(data=events, meta=ResponseMeta.now())


@router.post("/refresh/watchlist", response_model=DataResponse[dict])
async def refresh_watchlist_events(
    watchlist_id: Optional[int] = Query(None, description="Specific watchlist to refresh"),
    current_user: User = Depends(get_current_user),
    service: EconomicEventService = Depends(get_event_service),
) -> DataResponse[dict]:
    """
    Refresh events for all equities in user's watchlist(s).

    This may take some time for large watchlists.
    Consider using the background Celery task for automated updates.
    """
    count = await service.refresh_watchlist_events(
        user_id=current_user.id,
        watchlist_id=watchlist_id,
    )
    return DataResponse(
        data={"events_updated": count},
        meta=ResponseMeta.now(),
    )
