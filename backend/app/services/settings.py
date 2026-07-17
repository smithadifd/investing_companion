"""User settings service - manage user configuration and API keys."""

import base64
import logging
import uuid
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.user import User
from app.db.models.user_settings import UserSetting
from app.schemas.auth import AppSettings, AppSettingsUpdate

logger = logging.getLogger(__name__)

# Version tags for the secrets-at-rest ciphertext scheme. Stored values are
# prefixed with "<version>:" so the decrypt path knows which key produced them.
#
#   v1  -> legacy key: PBKDF2(SECRET_KEY, static salt). What the OLD code wrote.
#   v2  -> the dedicated ENCRYPTION_KEY (see config.ENCRYPTION_KEY).
#   (no prefix) -> a raw Fernet token written by the ORIGINAL code, before this
#                  scheme existed. Still decryptable via the legacy key.
#
# NON-BRICKING GUARANTEE: the legacy derivation below is frozen forever. Any
# ciphertext ever written (unprefixed legacy token, or v1:) stays decryptable
# even after ENCRYPTION_KEY is provisioned. Only NEW writes move to v2. The
# actual re-encryption of existing rows to v2 is a separate supervised
# migration, not something that happens at boot.
_VERSION_LEGACY = "v1"
_VERSION_PRIMARY = "v2"
# NEVER change this salt: existing ciphertext is derived from it.
_LEGACY_SALT = b"investing_companion_salt"
# Distinct salt for the PBKDF2 fallback when ENCRYPTION_KEY is a passphrase
# rather than a generated Fernet key. Decoupled from the legacy salt on purpose.
_ENCRYPTION_KEY_SALT = b"investing_companion_encryption_key_v2"


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
    SCHWAB_TOKEN = "SCHWAB_TOKEN"
    SCHWAB_EXPIRY_LAST_NOTIFIED = "SCHWAB_EXPIRY_LAST_NOTIFIED"
    # Explicit install-owner pointer (a global row with user_id NULL). Replaces
    # the old implicit "oldest active user" resolution used by background tasks.
    OWNER_USER_ID = "OWNER_USER_ID"

    # Keys that should be encrypted. DISCORD_WEBHOOK_URL is a bearer credential
    # (anyone with the URL can post to the channel), so it is encrypted at rest
    # like the API keys. Existing plaintext rows stay readable (the per-row
    # is_encrypted flag drives decryption) and get encrypted on next write.
    ENCRYPTED_KEYS = {
        CLAUDE_API_KEY,
        ALPHA_VANTAGE_API_KEY,
        POLYGON_API_KEY,
        SCHWAB_TOKEN,
        DISCORD_WEBHOOK_URL,
    }

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        # Legacy cipher (v1): derived from SECRET_KEY. Frozen — required to keep
        # decrypting anything the old code wrote.
        self._legacy_fernet = self._create_legacy_fernet()
        # Primary cipher (v2): the dedicated ENCRYPTION_KEY when provisioned,
        # else the legacy cipher (backward-compat fallback + warning).
        self._primary_fernet, self._has_dedicated_key = self._create_primary_fernet()
        # Try every known key when decrypting an unversioned legacy token.
        self._multi_fernet = MultiFernet([self._primary_fernet, self._legacy_fernet])

    @staticmethod
    def _create_legacy_fernet() -> Fernet:
        """Cipher derived from SECRET_KEY + static salt (the original scheme).

        Frozen forever: existing DB ciphertext depends on this exact derivation.
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_LEGACY_SALT,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(settings.SECRET_KEY.encode()))
        return Fernet(key)

    @staticmethod
    def _create_primary_fernet() -> tuple[Fernet, bool]:
        """Return (cipher, has_dedicated_key) for the primary (v2) key.

        Prefers the dedicated ENCRYPTION_KEY. If it is unset, falls back to the
        legacy SECRET_KEY-derived cipher and logs a warning — so nothing breaks
        during the transition, but the coupling is loud.
        """
        raw = (settings.ENCRYPTION_KEY or "").strip()
        if not raw:
            logger.warning(
                "ENCRYPTION_KEY is not set; encrypting secrets with the legacy "
                "SECRET_KEY-derived key. Provision ENCRYPTION_KEY to decouple "
                "data encryption from JWT signing."
            )
            return SettingsService._create_legacy_fernet(), False
        return Fernet(SettingsService._normalize_encryption_key(raw)), True

    @staticmethod
    def _normalize_encryption_key(raw: str) -> bytes:
        """Coerce ENCRYPTION_KEY into a valid 32-byte urlsafe-base64 Fernet key.

        A value that is already a valid Fernet key is used verbatim (the
        recommended path — generate one with ``Fernet.generate_key()``). Any
        other string is stretched deterministically via PBKDF2 so operators can
        supply a passphrase without bricking round-trips.
        """
        candidate = raw.encode()
        try:
            # A real Fernet key is urlsafe-b64 that decodes to exactly 32 bytes.
            if len(base64.urlsafe_b64decode(candidate)) == 32:
                Fernet(candidate)  # validates format
                return candidate
        except Exception:
            pass
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_ENCRYPTION_KEY_SALT,
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(candidate))

    def _encrypt(self, value: str) -> str:
        """Encrypt a value, tagging it with the producing key's version.

        Writes v2 when a dedicated ENCRYPTION_KEY is set, else v1 (legacy
        derivation) so the value stays decryptable during the transition.
        """
        if self._has_dedicated_key:
            token = self._primary_fernet.encrypt(value.encode()).decode()
            return f"{_VERSION_PRIMARY}:{token}"
        token = self._legacy_fernet.encrypt(value.encode()).decode()
        return f"{_VERSION_LEGACY}:{token}"

    def _decrypt(self, encrypted_value: str) -> str:
        """Decrypt a value written under any scheme version (non-bricking).

        Routes by version prefix; an unprefixed value is a raw Fernet token
        from the original code and is tried against every known key.

        A decryption failure is re-raised (callers still fail-safe to None) but
        is logged LOUDLY first: a value stored as ciphertext that won't decrypt
        almost always means a misconfiguration — e.g. ENCRYPTION_KEY was dropped
        or changed — not a genuinely-absent secret. Without this, an accidental
        env change would make every v2 secret silently vanish. No plaintext or
        key material is ever logged.
        """
        try:
            if encrypted_value.startswith(f"{_VERSION_PRIMARY}:"):
                token = encrypted_value[len(_VERSION_PRIMARY) + 1:]
                return self._primary_fernet.decrypt(token.encode()).decode()
            if encrypted_value.startswith(f"{_VERSION_LEGACY}:"):
                token = encrypted_value[len(_VERSION_LEGACY) + 1:]
                return self._legacy_fernet.decrypt(token.encode()).decode()
            # Unversioned: a raw Fernet token from before this scheme existed.
            return self._multi_fernet.decrypt(encrypted_value.encode()).decode()
        except (InvalidToken, ValueError) as exc:
            prefix = encrypted_value.split(":", 1)[0]
            version = (
                prefix
                if prefix in (_VERSION_PRIMARY, _VERSION_LEGACY)
                else "unversioned"
            )
            logger.error(
                "Failed to decrypt a stored secret (version=%s): %s. This is a "
                "DECRYPT FAILURE, not an absent value — it usually means "
                "ENCRYPTION_KEY is unset/incorrect or the ciphertext is corrupt. "
                "The value will be treated as absent. No plaintext is logged.",
                version,
                type(exc).__name__,
            )
            raise

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

    async def get_owner_user_id(self) -> Optional[uuid.UUID]:
        """Resolve the install owner deterministically.

        Replaces the old implicit "first/oldest active user" behavior:

        1. An explicit ``OWNER_USER_ID`` global setting, when its user is active.
        2. Otherwise the sole active user (unambiguous single-user install).
        3. Otherwise ``None`` — an ambiguous multi-user install with no explicit
           owner is never resolved by guessing; callers degrade gracefully.
        """
        explicit = await self.db.scalar(
            select(UserSetting.value).where(
                UserSetting.key == self.OWNER_USER_ID,
                UserSetting.user_id.is_(None),
                UserSetting.value.isnot(None),
            )
        )
        if explicit:
            try:
                owner_id: Optional[uuid.UUID] = uuid.UUID(explicit)
            except (ValueError, TypeError):
                owner_id = None
            if owner_id is not None:
                is_active = await self.db.scalar(
                    select(User.is_active).where(User.id == owner_id)
                )
                if is_active:
                    return owner_id

        active_ids = (
            await self.db.execute(
                select(User.id).where(User.is_active.is_(True)).limit(2)
            )
        ).scalars().all()
        if len(active_ids) == 1:
            return active_ids[0]
        return None

    async def set_owner_user_id(self, user_id: uuid.UUID) -> None:
        """Record the explicit install owner (global OWNER_USER_ID setting)."""
        await self.set_setting(self.OWNER_USER_ID, str(user_id), user_id=None)

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
