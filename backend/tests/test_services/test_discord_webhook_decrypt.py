"""Regression: DISCORD_WEBHOOK_URL must be decrypted before use as a URL.

S8 (fix #2) moved DISCORD_WEBHOOK_URL into SettingsService.ENCRYPTED_KEYS, so
new/updated rows are stored as versioned ciphertext (``v2:...``). The Discord
notifier previously read ``UserSetting.value`` directly on the assumption it
was always plaintext ("Discord webhook URLs are not encrypted, use directly").
Without decrypting, every webhook POST would target ciphertext instead of the
real Discord URL and silently fail. This locks in the fix.

Uses the `engine` fixture directly (not the savepoint-rollback `db` fixture):
the notifier opens its own DB session via app.db.session.AsyncSessionLocal, a
module-level sessionmaker bound to a *different* connection than the `db`
fixture's, so a write inside `db`'s savepoint would be invisible to it. We
point AsyncSessionLocal at the same test engine instead, write for real, and
clean up in a finally block.
"""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.db.session as db_session_module
from app.core.config import settings as app_settings
from app.db.models.user_settings import UserSetting
from app.services.notifications.discord import DiscordNotificationService
from app.services.settings import SettingsService


@pytest.mark.asyncio
async def test_encrypted_discord_webhook_row_is_decrypted_before_use(
    engine, monkeypatch
):
    monkeypatch.setattr(
        app_settings, "ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    monkeypatch.setattr(app_settings, "DISCORD_WEBHOOK_URL", "")  # no env override

    session_local = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session_module, "AsyncSessionLocal", session_local)

    plaintext_url = "https://discord.com/api/webhooks/999/regression-test"
    try:
        async with session_local() as session:
            svc = SettingsService(session)
            await svc.set_setting(
                SettingsService.DISCORD_WEBHOOK_URL, plaintext_url, user_id=None
            )

        # Confirm the row is actually stored as ciphertext (proves this test
        # would have caught the bug: reading .value raw yields "v2:...").
        async with session_local() as session:
            stored = (
                await session.execute(
                    select(UserSetting).where(
                        UserSetting.key == "DISCORD_WEBHOOK_URL"
                    )
                )
            ).scalar_one()
            assert stored.is_encrypted is True
            assert stored.value.startswith("v2:")

        notifier = DiscordNotificationService(webhook_url=None)
        resolved = await notifier._get_webhook_url()

        assert resolved == plaintext_url
        assert resolved is not None and not resolved.startswith("v2:")
    finally:
        async with session_local() as session:
            await session.execute(
                delete(UserSetting).where(UserSetting.key == "DISCORD_WEBHOOK_URL")
            )
            await session.commit()


@pytest.mark.asyncio
async def test_plaintext_legacy_row_still_used_as_is(engine, monkeypatch):
    """Rows saved before this PR (is_encrypted=False) keep working unchanged."""
    monkeypatch.setattr(app_settings, "DISCORD_WEBHOOK_URL", "")

    session_local = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session_module, "AsyncSessionLocal", session_local)

    plaintext_url = "https://discord.com/api/webhooks/111/legacy-plaintext"
    try:
        async with session_local() as session:
            session.add(
                UserSetting(
                    user_id=None,
                    key="DISCORD_WEBHOOK_URL",
                    value=plaintext_url,
                    is_encrypted=False,
                )
            )
            await session.commit()

        notifier = DiscordNotificationService(webhook_url=None)
        resolved = await notifier._get_webhook_url()

        assert resolved == plaintext_url
    finally:
        async with session_local() as session:
            await session.execute(
                delete(UserSetting).where(UserSetting.key == "DISCORD_WEBHOOK_URL")
            )
            await session.commit()
