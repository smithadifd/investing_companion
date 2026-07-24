"""Export endpoints - structured state for external AI advisors."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import DataResponse
from app.schemas.context_pack import ContextPack
from app.schemas.handoff import HandoffReceiptCreate, HandoffReceiptResponse
from app.schemas.outbox import OutboxPublishResult, OutboxStatusResponse
from app.services.context_pack import ContextPackService, render_markdown
from app.services.context_pack_outbox import ContextPackOutboxService
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
) -> ContextPack | PlainTextResponse:
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


def get_outbox_service(
    db: AsyncSession = Depends(get_db),
) -> ContextPackOutboxService:
    return ContextPackOutboxService(db)


@router.get("/outbox-status", response_model=DataResponse[OutboxStatusResponse])
async def get_outbox_status(
    current_user: User = Depends(get_current_user),
) -> DataResponse[OutboxStatusResponse]:
    """Report whether an outbox is configured and when it was last published.

    Lets the UI show or disable the publish action without trying it first.
    """
    s = ContextPackOutboxService.status()
    return DataResponse(
        data=OutboxStatusResponse(
            configured=s.configured,
            dir=s.dir,
            last_published_at=s.last_published_at,
            last_file=s.last_file,
        )
    )


@router.post(
    "/context-pack/publish",
    response_model=DataResponse[OutboxPublishResult],
    status_code=status.HTTP_201_CREATED,
)
async def publish_context_pack(
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: ContextPackOutboxService = Depends(get_outbox_service),
) -> DataResponse[OutboxPublishResult]:
    """Write the current context pack to the outbox directory.

    A host-side rclone job syncs the outbox to the advisor's Drive folder; the
    app only writes plain files. Returns 409 if no outbox is configured.
    """
    result = await service.publish(current_user.id)
    return DataResponse(
        data=OutboxPublishResult(
            latest_path=result.latest_path,
            history_path=result.history_path,
            generated_at=result.generated_at,
        )
    )


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
