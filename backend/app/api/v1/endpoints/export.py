"""Export endpoints - structured state for external AI advisors."""

import logging
from typing import Literal, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.context_pack import ContextPack
from app.services.context_pack import ContextPackService, render_markdown

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
