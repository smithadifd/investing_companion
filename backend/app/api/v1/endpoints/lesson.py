"""Lesson API endpoints - the learning loop's capture and journal."""


from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import (
    DataResponse,
    ListResponse,
    PaginatedMeta,
    ResponseMeta,
)
from app.schemas.lesson import LessonCreate, LessonResponse, LessonUpdate
from app.services.lesson import LessonService

router = APIRouter()


def get_lesson_service(db: AsyncSession = Depends(get_db)) -> LessonService:
    """Dependency to get lesson service instance."""
    return LessonService(db)


@router.get("", response_model=ListResponse[LessonResponse])
async def list_lessons(
    symbol: str | None = Query(None, description="Filter by equity symbol"),
    tag: str | None = Query(None, description="Filter by tag (case-insensitive)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    service: LessonService = Depends(get_lesson_service),
) -> ListResponse[LessonResponse]:
    """List lessons, newest first."""
    lessons, total = await service.list_lessons(
        user_id=current_user.id,
        symbol=symbol,
        tag=tag,
        limit=limit,
        offset=offset,
    )
    meta = PaginatedMeta(
        total=total,
        page=offset // limit + 1,
        per_page=limit,
        pages=max(1, -(-total // limit)),
    )
    return ListResponse(data=lessons, meta=meta)


@router.post(
    "", response_model=DataResponse[LessonResponse], status_code=status.HTTP_201_CREATED
)
async def create_lesson(
    data: LessonCreate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: LessonService = Depends(get_lesson_service),
) -> DataResponse[LessonResponse]:
    """
    Capture a lesson.

    Provide `trade_id` (the closing trade; equity derived from it), or
    `equity_id` / `symbol` for a standalone lesson.
    """
    if data.trade_id is None and data.equity_id is None and not data.symbol:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One of trade_id, equity_id, or symbol must be provided",
        )

    lesson = await service.create_lesson(current_user.id, data)
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create lesson. Trade or equity not found.",
        )
    return DataResponse(data=lesson, meta=ResponseMeta.now())


@router.get("/{lesson_id}", response_model=DataResponse[LessonResponse])
async def get_lesson(
    lesson_id: int,
    current_user: User = Depends(get_current_user),
    service: LessonService = Depends(get_lesson_service),
) -> DataResponse[LessonResponse]:
    """Get a single lesson by ID."""
    lesson = await service.get_lesson(lesson_id, current_user.id)
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found"
        )
    return DataResponse(data=lesson, meta=ResponseMeta.now())


@router.put("/{lesson_id}", response_model=DataResponse[LessonResponse])
async def update_lesson(
    lesson_id: int,
    data: LessonUpdate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: LessonService = Depends(get_lesson_service),
) -> DataResponse[LessonResponse]:
    """Update a lesson. An explicit `trade_id: null` unlinks the trade."""
    try:
        lesson = await service.update_lesson(lesson_id, current_user.id, data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found"
        )
    return DataResponse(data=lesson, meta=ResponseMeta.now())


@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: int,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: LessonService = Depends(get_lesson_service),
) -> None:
    """Delete a lesson."""
    deleted = await service.delete_lesson(lesson_id, current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found"
        )
