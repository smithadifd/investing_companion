"""AI analysis endpoints."""

import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.ai import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    AISettingsResponse,
    AISettingsUpdate,
)
from app.schemas.common import DataResponse
from app.services.ai import AIService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


def get_ai_service(db: AsyncSession = Depends(get_db)) -> AIService:
    """Dependency to get AI service instance."""
    return AIService(db)


@router.get("/settings", response_model=DataResponse[AISettingsResponse])
async def get_ai_settings(
    current_user: User = Depends(get_current_user),
    service: AIService = Depends(get_ai_service),
) -> DataResponse[AISettingsResponse]:
    """
    Get current AI settings.
    """
    data = await service.get_settings()
    return DataResponse(data=data)


@router.put("/settings", response_model=DataResponse[AISettingsResponse])
async def update_ai_settings(
    data: AISettingsUpdate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: AIService = Depends(get_ai_service),
) -> DataResponse[AISettingsResponse]:
    """
    Update AI settings including API key and custom instructions.
    """
    result = await service.update_settings(data)
    return DataResponse(data=result)


@router.post("/analyze", response_model=DataResponse[AIAnalysisResponse])
async def analyze(
    request: AIAnalysisRequest,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: AIService = Depends(get_ai_service),
) -> DataResponse[AIAnalysisResponse]:
    """
    Perform AI analysis on equity, ratio, or general topic.
    Returns complete response (non-streaming).
    """
    try:
        result = await service.analyze(request)
        return DataResponse(data=result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"AI analysis error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to perform analysis",
        )


@router.post("/analyze/stream")
async def analyze_stream(
    request: AIAnalysisRequest,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: AIService = Depends(get_ai_service),
):
    """
    Perform AI analysis with streaming response (SSE).
    """

    async def generate() -> AsyncGenerator[str, None]:
        try:
            async for chunk in service.analyze_stream(request):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except ValueError as e:
            yield f"data: ERROR: {str(e)}\n\n"
        except RuntimeError as e:
            yield f"data: ERROR: {str(e)}\n\n"
        except Exception as e:
            logger.error(f"AI streaming error: {e}")
            yield "data: ERROR: Failed to perform analysis\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
