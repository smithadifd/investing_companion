"""User settings API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth import AppSettings, AppSettingsUpdate
from app.schemas.common import DataResponse, ResponseMeta
from app.services.notifications.discord import discord_service
from app.services.settings import SettingsService

router = APIRouter()


@router.get("", response_model=DataResponse[AppSettings])
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[AppSettings]:
    """Get current user's application settings."""
    settings_service = SettingsService(db)
    app_settings = await settings_service.get_app_settings(current_user.id)
    return DataResponse(data=app_settings, meta=ResponseMeta.now())


@router.patch("", response_model=DataResponse[AppSettings])
async def update_settings(
    updates: AppSettingsUpdate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[AppSettings]:
    """Update current user's application settings.

    Send empty string to clear a setting.
    """
    settings_service = SettingsService(db)
    app_settings = await settings_service.update_app_settings(updates, current_user.id)

    # Clear Discord service cache if webhook URL was updated
    if updates.discord_webhook_url is not None:
        discord_service.clear_cache()

    return DataResponse(data=app_settings, meta=ResponseMeta.now())
