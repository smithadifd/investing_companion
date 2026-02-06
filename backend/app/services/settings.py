"""User settings service - manage user configuration and API keys."""

import base64
import uuid
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.user_settings import UserSetting
from app.schemas.auth import AppSettings, AppSettingsUpdate


class SettingsService:
    """Service for user settings operations."""

    # Settings keys
    CLAUDE_API_KEY = "CLAUDE_API_KEY"
    ALPHA_VANTAGE_API_KEY = "ALPHA_VANTAGE_API_KEY"
    POLYGON_API_KEY = "POLYGON_API_KEY"
    DISCORD_WEBHOOK_URL = "DISCORD_WEBHOOK_URL"
    DEFAULT_WATCHLIST_ID = "DEFAULT_WATCHLIST_ID"
    THEME = "THEME"
    MORNING_NOTIFICATION_TIME = "MORNING_NOTIFICATION_TIME"
    EOD_NOTIFICATION_TIME = "EOD_NOTIFICATION_TIME"
    MORNING_NOTIFICATION_LAST_SENT = "MORNING_NOTIFICATION_LAST_SENT"
    EOD_NOTIFICATION_LAST_SENT = "EOD_NOTIFICATION_LAST_SENT"

    # Keys that should be encrypted
    ENCRYPTED_KEYS = {
        CLAUDE_API_KEY,
        ALPHA_VANTAGE_API_KEY,
        POLYGON_API_KEY,
    }

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._fernet = self._create_fernet()

    def _create_fernet(self) -> Fernet:
        """Create Fernet cipher using app secret key."""
        # Derive a key from the secret
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"investing_companion_salt",  # Static salt is fine here
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(settings.SECRET_KEY.encode()))
        return Fernet(key)

    def _encrypt(self, value: str) -> str:
        """Encrypt a value."""
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, encrypted_value: str) -> str:
        """Decrypt a value."""
        return self._fernet.decrypt(encrypted_value.encode()).decode()

    async def get_setting(
        self,
        key: str,
        user_id: Optional[uuid.UUID] = None,
    ) -> Optional[str]:
        """Get a single setting value."""
        stmt = select(UserSetting).where(
            UserSetting.key == key,
            UserSetting.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        setting = result.scalar_one_or_none()

        if not setting or setting.value is None:
            return None

        if setting.is_encrypted:
            try:
                return self._decrypt(setting.value)
            except Exception:
                return None
        return setting.value

    async def set_setting(
        self,
        key: str,
        value: Optional[str],
        user_id: Optional[uuid.UUID] = None,
        description: Optional[str] = None,
    ) -> UserSetting:
        """Set a setting value."""
        is_encrypted = key in self.ENCRYPTED_KEYS

        # Check if setting exists
        stmt = select(UserSetting).where(
            UserSetting.key == key,
            UserSetting.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        setting = result.scalar_one_or_none()

        if value is not None and is_encrypted:
            stored_value = self._encrypt(value)
        else:
            stored_value = value

        if setting:
            setting.value = stored_value
            setting.is_encrypted = is_encrypted
            if description is not None:
                setting.description = description
        else:
            setting = UserSetting(
                user_id=user_id,
                key=key,
                value=stored_value,
                is_encrypted=is_encrypted,
                description=description,
            )
            self.db.add(setting)

        await self.db.commit()
        await self.db.refresh(setting)
        return setting

    async def delete_setting(
        self,
        key: str,
        user_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """Delete a setting."""
        stmt = delete(UserSetting).where(
            UserSetting.key == key,
            UserSetting.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0

    async def get_app_settings(
        self,
        user_id: Optional[uuid.UUID] = None,
    ) -> AppSettings:
        """Get all application settings as a structured object."""
        # Fetch all settings for the user
        stmt = select(UserSetting).where(UserSetting.user_id == user_id)
        result = await self.db.execute(stmt)
        settings_records = result.scalars().all()

        # Build settings dict
        settings_dict = {}
        for setting in settings_records:
            value = setting.value
            if setting.is_encrypted and value:
                try:
                    value = self._decrypt(value)
                except Exception:
                    value = None
            settings_dict[setting.key] = value

        # Map to AppSettings
        default_watchlist_id = settings_dict.get(self.DEFAULT_WATCHLIST_ID)
        if default_watchlist_id:
            try:
                default_watchlist_id = int(default_watchlist_id)
            except ValueError:
                default_watchlist_id = None

        return AppSettings(
            claude_api_key=self._mask_key(settings_dict.get(self.CLAUDE_API_KEY)),
            alpha_vantage_api_key=self._mask_key(settings_dict.get(self.ALPHA_VANTAGE_API_KEY)),
            polygon_api_key=self._mask_key(settings_dict.get(self.POLYGON_API_KEY)),
            discord_webhook_url=self._mask_url(settings_dict.get(self.DISCORD_WEBHOOK_URL)),
            default_watchlist_id=default_watchlist_id,
            theme=settings_dict.get(self.THEME, "dark"),
            morning_notification_time=settings_dict.get(self.MORNING_NOTIFICATION_TIME, "08:00"),
            eod_notification_time=settings_dict.get(self.EOD_NOTIFICATION_TIME, "16:30"),
        )

    async def update_app_settings(
        self,
        updates: AppSettingsUpdate,
        user_id: Optional[uuid.UUID] = None,
    ) -> AppSettings:
        """Update application settings."""
        if updates.claude_api_key is not None:
            if updates.claude_api_key == "":
                await self.delete_setting(self.CLAUDE_API_KEY, user_id)
            else:
                await self.set_setting(
                    self.CLAUDE_API_KEY,
                    updates.claude_api_key,
                    user_id,
                    "Claude API key for AI analysis",
                )

        if updates.alpha_vantage_api_key is not None:
            if updates.alpha_vantage_api_key == "":
                await self.delete_setting(self.ALPHA_VANTAGE_API_KEY, user_id)
            else:
                await self.set_setting(
                    self.ALPHA_VANTAGE_API_KEY,
                    updates.alpha_vantage_api_key,
                    user_id,
                    "Alpha Vantage API key",
                )

        if updates.polygon_api_key is not None:
            if updates.polygon_api_key == "":
                await self.delete_setting(self.POLYGON_API_KEY, user_id)
            else:
                await self.set_setting(
                    self.POLYGON_API_KEY,
                    updates.polygon_api_key,
                    user_id,
                    "Polygon.io API key",
                )

        if updates.discord_webhook_url is not None:
            if updates.discord_webhook_url == "":
                await self.delete_setting(self.DISCORD_WEBHOOK_URL, user_id)
            else:
                await self.set_setting(
                    self.DISCORD_WEBHOOK_URL,
                    updates.discord_webhook_url,
                    user_id,
                    "Discord webhook URL for notifications",
                )

        if updates.default_watchlist_id is not None:
            await self.set_setting(
                self.DEFAULT_WATCHLIST_ID,
                str(updates.default_watchlist_id),
                user_id,
                "Default watchlist ID",
            )

        if updates.theme is not None:
            await self.set_setting(
                self.THEME,
                updates.theme,
                user_id,
                "UI theme preference",
            )

        if updates.morning_notification_time is not None:
            await self.set_setting(
                self.MORNING_NOTIFICATION_TIME,
                updates.morning_notification_time,
                user_id,
                "Morning notification time (ET)",
            )

        if updates.eod_notification_time is not None:
            await self.set_setting(
                self.EOD_NOTIFICATION_TIME,
                updates.eod_notification_time,
                user_id,
                "End-of-day notification time (ET)",
            )

        return await self.get_app_settings(user_id)

    def _mask_key(self, key: Optional[str]) -> Optional[str]:
        """Mask an API key for display (show first/last 4 chars)."""
        if not key:
            return None
        if len(key) <= 12:
            return "*" * len(key)
        return f"{key[:4]}...{key[-4:]}"

    def _mask_url(self, url: Optional[str]) -> Optional[str]:
        """Mask a URL for display."""
        if not url:
            return None
        if "discord" in url.lower():
            # Just show that it's configured
            return "https://discord.com/api/webhooks/***"
        return url

    async def get_unmasked_setting(
        self,
        key: str,
        user_id: Optional[uuid.UUID] = None,
    ) -> Optional[str]:
        """Get unmasked setting value for internal use."""
        return await self.get_setting(key, user_id)
