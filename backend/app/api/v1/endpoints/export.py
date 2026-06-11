"""Export endpoints - structured state for external AI advisors."""

import logging
from typing import Literal, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.context_pack import ContextPack
from app.schemas.handoff import HandoffReceiptCreate, HandoffReceiptResponse
from app.services.context_pack import ContextPackService, render_markdown
from app.services.handoff import HandoffService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_context_pack_service(db: AsyncSession = Depends(get_db)) -> ContextPackService:
    return ContextPackService(db)


@router.get("/context-pack", response_model=None)
async def get_context_pack(
    format: Literal["json", "markdown"] = Query(
        "json", description="json for tooling, markdown for pasting into a conversation"
    ),
    current_user: User = Depends(get_current_user),
    service: ContextPackService = Depends(get_context_pack_service),
) -> Union[ContextPack, PlainTextResponse]:
    """Build the versioned context pack for the current user."""
    try:
        pack = await service.build(current_user.id)
    except Exception as e:
        logger.error(f"Context pack build failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to build context pack",
        )

    if format == "markdown":
        return PlainTextResponse(
            render_markdown(pack), media_type="text/markdown; charset=utf-8"
        )
    return pack


def get_handoff_service(db: AsyncSession = Depends(get_db)) -> HandoffService:
    return HandoffService(db)


@router.post(
    "/handoff-receipts",
    response_model=HandoffReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_handoff_receipt(
    data: HandoffReceiptCreate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: HandoffService = Depends(get_handoff_service),
) -> HandoffReceiptResponse:
    """Record the execution outcome of an advisor handoff block.

    Posted by the executor (Claude Code) after applying a handoff; the
    receipt is folded into subsequent context packs so the advisor's
    mental model tracks what actually happened.
    """
    return await service.record(data, user_id=current_user.id)
