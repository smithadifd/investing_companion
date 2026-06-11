"""Dashboard endpoints - decision-first aggregations."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import DataResponse
from app.schemas.dashboard import NeedsAttentionResponse
from app.services.needs_attention import build_needs_attention

router = APIRouter()


@router.get("/needs-attention", response_model=DataResponse[NeedsAttentionResponse])
async def get_needs_attention(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[NeedsAttentionResponse]:
    """The morning pulse's ⚡ section as structured data for the dashboard."""
    items = await build_needs_attention(db)
    return DataResponse(data=NeedsAttentionResponse(items=items))
