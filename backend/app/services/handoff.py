"""Handoff receipt service - records and lists handoff execution outcomes."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.handoff import HandoffLog
from app.schemas.handoff import (
    HandoffActionResult,
    HandoffReceiptCreate,
    HandoffReceiptResponse,
)

logger = logging.getLogger(__name__)


class HandoffService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record(
        self, data: HandoffReceiptCreate, user_id: UUID | None = None
    ) -> HandoffReceiptResponse:
        counts = {"applied": 0, "skipped": 0, "flagged": 0}
        for action in data.actions:
            counts[action.result] += 1

        log = HandoffLog(
            user_id=user_id,
            source=data.source,
            summary=data.summary,
            actions=[a.model_dump() for a in data.actions],
            applied_count=counts["applied"],
            skipped_count=counts["skipped"],
            flagged_count=counts["flagged"],
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        logger.info(
            f"Handoff receipt {log.id}: {counts['applied']} applied, "
            f"{counts['skipped']} skipped, {counts['flagged']} flagged"
        )
        return self._to_response(log)

    async def recent(self, limit: int = 5) -> list[HandoffReceiptResponse]:
        stmt = (
            select(HandoffLog)
            .order_by(HandoffLog.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return [self._to_response(row) for row in result.scalars().all()]

    @staticmethod
    def _to_response(log: HandoffLog) -> HandoffReceiptResponse:
        return HandoffReceiptResponse(
            id=log.id,
            source=log.source,
            summary=log.summary,
            actions=[HandoffActionResult(**a) for a in log.actions],
            applied_count=log.applied_count,
            skipped_count=log.skipped_count,
            flagged_count=log.flagged_count,
            created_at=log.created_at,
        )
