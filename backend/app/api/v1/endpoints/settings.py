"""User settings API endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth import AppSettings, AppSettingsUpdate
from app.schemas.common import DataResponse, ResponseMeta
from app.services.settings import SettingsService

router = APIRouter()


def create_meta() -> ResponseMeta:
    """Create response metadata."""
    return ResponseMeta(timestamp=datetime.utcnow())


@router.get("", response_model=DataResponse[AppSettings])
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[AppSettings]:
    """Get current user's application settings."""
    settings_service = SettingsService(db)
    app_settings = await settings_service.get_app_settings(current_user.id)
    return DataResponse(data=app_settings, meta=create_meta())


@router.patch("", response_model=DataResponse[AppSettings])
async def update_settings(
    updates: AppSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[AppSettings]:
    """Update current user's application settings.

    Send empty string to clear a setting.
    """
    settings_service = SettingsService(db)
    app_settings = await settings_service.update_app_settings(updates, current_user.id)
    return DataResponse(data=app_settings, meta=create_meta())
