"""Lesson service - capture and resurfacing for the learning loop.

The "similar setup" matching rule (deterministic, no scoring model):

A lesson is relevant to a set of involved symbols S (e.g. the symbols a
trigger's linked alerts watch) when ANY of:

1. **Same symbol** - the lesson's equity is in S.
2. **Shared theme** - the lesson's equity shares a theme watchlist (any
   non-default watchlist) with a symbol in S.
3. **Tag match** - one of the lesson's tags (stored lowercase) equals a
   symbol in S or the name of a theme watchlist containing a symbol in S,
   compared case-insensitively.

Matches are returned most-recent-first and capped by the caller (the
trade-readiness card shows at most MAX_LESSONS_PER_ITEM per trigger).
Both the readiness card and the context pack consume this service so the
two surfaces can't drift.
"""

from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.equity import Equity
from app.db.models.lesson import Lesson
from app.db.models.trade import Trade
from app.db.models.watchlist import Watchlist, WatchlistItem
from app.schemas.lesson import LessonCreate, LessonResponse, LessonUpdate
from app.services.equity import EquityService

# Cap on lessons attached per readiness item - recency beats completeness
MAX_LESSONS_PER_ITEM = 3


class LessonService:
    """CRUD + similar-setup matching for lessons."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.equity_service = EquityService(db)

    async def list_lessons(
        self,
        user_id: UUID,
        symbol: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[LessonResponse], int]:
        conditions = [Lesson.user_id == user_id]
        if symbol:
            conditions.append(
                Lesson.equity_id.in_(
                    select(Equity.id).where(Equity.symbol == symbol.upper())
                )
            )
        if tag:
            conditions.append(Lesson.tags.contains([tag.strip().lower()]))

        total = (
            await self.db.execute(
                select(func.count(Lesson.id)).where(and_(*conditions))
            )
        ).scalar() or 0

        stmt = (
            select(Lesson)
            .options(selectinload(Lesson.equity))
            .where(and_(*conditions))
            .order_by(Lesson.created_at.desc(), Lesson.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return [self._to_response(les) for les in result.scalars().all()], total

    async def get_lesson(
        self, lesson_id: int, user_id: UUID
    ) -> LessonResponse | None:
        lesson = await self._get(lesson_id, user_id)
        return self._to_response(lesson) if lesson else None

    async def create_lesson(
        self, user_id: UUID, data: LessonCreate
    ) -> LessonResponse | None:
        """Resolve the equity from trade_id, equity_id, or symbol (in that order)."""
        equity = None
        trade_id = None
        if data.trade_id is not None:
            trade = await self.db.scalar(
                select(Trade).where(
                    Trade.id == data.trade_id, Trade.user_id == user_id
                )
            )
            if not trade:
                return None
            trade_id = trade.id
            equity = await self.db.get(Equity, trade.equity_id)
        elif data.equity_id is not None:
            equity = await self.db.get(Equity, data.equity_id)
        elif data.symbol:
            equity = await self.equity_service.get_or_create_equity(data.symbol)

        if not equity:
            return None

        lesson = Lesson(
            user_id=user_id,
            trade_id=trade_id,
            equity_id=equity.id,
            thesis_outcome=data.thesis_outcome.value,
            lesson=data.lesson,
            tags=data.tags or None,
        )
        self.db.add(lesson)
        await self.db.commit()
        await self.db.refresh(lesson)
        return self._to_response(lesson)

    async def update_lesson(
        self, lesson_id: int, user_id: UUID, data: LessonUpdate
    ) -> LessonResponse | None:
        lesson = await self._get(lesson_id, user_id)
        if not lesson:
            return None

        if data.thesis_outcome is not None:
            lesson.thesis_outcome = data.thesis_outcome.value
        if data.lesson is not None:
            lesson.lesson = data.lesson
        # exclude_unset semantics: explicit null clears, omitted leaves as-is
        if "tags" in data.model_fields_set:
            lesson.tags = data.tags or None
        if "trade_id" in data.model_fields_set:
            if data.trade_id is not None:
                trade = await self.db.scalar(
                    select(Trade).where(
                        Trade.id == data.trade_id, Trade.user_id == user_id
                    )
                )
                if not trade:
                    raise ValueError(f"Unknown trade id: {data.trade_id}")
                lesson.trade_id = trade.id
            else:
                lesson.trade_id = None

        await self.db.commit()
        await self.db.refresh(lesson)
        return self._to_response(lesson)

    async def delete_lesson(self, lesson_id: int, user_id: UUID) -> bool:
        lesson = await self._get(lesson_id, user_id)
        if not lesson:
            return False
        await self.db.delete(lesson)
        await self.db.commit()
        return True

    async def relevant_lessons(
        self,
        user_id: UUID,
        symbols: list[str],
        limit: int = MAX_LESSONS_PER_ITEM,
    ) -> list[LessonResponse]:
        """Lessons matching the involved symbols per the module's matching rule."""
        involved = {s.upper() for s in symbols}
        if not involved:
            return []

        # Theme watchlists (non-default) and their member symbols
        stmt = (
            select(Watchlist.name, Equity.symbol)
            .join(WatchlistItem, WatchlistItem.watchlist_id == Watchlist.id)
            .join(Equity, Equity.id == WatchlistItem.equity_id)
            .where(Watchlist.is_default.is_(False))
        )
        themes: dict[str, set[str]] = {}
        for name, sym in (await self.db.execute(stmt)).all():
            themes.setdefault(name, set()).add(sym.upper())

        shared_themes = {
            name for name, members in themes.items() if members & involved
        }
        theme_symbols = set().union(
            *(themes[name] for name in shared_themes)
        ) if shared_themes else set()
        match_keys = {s.lower() for s in involved} | {
            t.lower() for t in shared_themes
        }

        stmt = (
            select(Lesson)
            .options(selectinload(Lesson.equity))
            .where(Lesson.user_id == user_id)
            .order_by(Lesson.created_at.desc(), Lesson.id.desc())
        )
        matched: list[LessonResponse] = []
        for lesson in (await self.db.execute(stmt)).scalars():
            symbol = lesson.equity.symbol.upper()
            tags = [t.lower() for t in (lesson.tags or [])]
            if (
                symbol in involved
                or symbol in theme_symbols
                or any(t in match_keys for t in tags)
            ):
                matched.append(self._to_response(lesson))
                if len(matched) >= limit:
                    break
        return matched

    async def recent_lessons(
        self, user_id: UUID, limit: int = 20
    ) -> list[LessonResponse]:
        """Most recent lessons, for the context pack's journal section."""
        lessons, _ = await self.list_lessons(user_id, limit=limit)
        return lessons

    async def _get(self, lesson_id: int, user_id: UUID) -> Lesson | None:
        return await self.db.scalar(
            select(Lesson)
            .options(selectinload(Lesson.equity))
            .where(Lesson.id == lesson_id, Lesson.user_id == user_id)
        )

    def _to_response(self, lesson: Lesson) -> LessonResponse:
        return LessonResponse(
            id=lesson.id,
            trade_id=lesson.trade_id,
            equity_id=lesson.equity_id,
            symbol=lesson.equity.symbol,
            thesis_outcome=lesson.thesis_outcome,
            lesson=lesson.lesson,
            tags=lesson.tags or [],
            created_at=lesson.created_at,
            updated_at=lesson.updated_at,
        )
