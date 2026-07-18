"""Tests for the three Tier-1 advisory-agent enable toggles on AppSettings.

Schema + rails only (sub-PR 1, see docs/issues/014-intelligent-agents.md) -
these cover that the toggles default OFF and round-trip correctly through
SettingsService, the same read/write path the Settings page and the
follow-up agents' guard (app.services.agents.guards) both use. Needs a real
Postgres connection (the ``db`` fixture) - runs in CI, not necessarily
locally if Postgres isn't available.
"""

from app.schemas.auth import AppSettingsUpdate
from app.services.settings import SettingsService
from tests.factories import create_test_user


async def test_agent_toggles_default_false_when_unset(db):
    user = await create_test_user(db, email="toggles-default@example.com")
    settings_service = SettingsService(db)

    app_settings = await settings_service.get_app_settings(user.id)

    assert app_settings.news_agent_enabled is False
    assert app_settings.trade_journal_agent_enabled is False
    assert app_settings.strategy_agent_enabled is False


async def test_agent_toggles_round_trip_through_update_and_get(db):
    user = await create_test_user(db, email="toggles-roundtrip@example.com")
    settings_service = SettingsService(db)

    await settings_service.update_app_settings(
        AppSettingsUpdate(news_agent_enabled=True, strategy_agent_enabled=True),
        user.id,
    )
    app_settings = await settings_service.get_app_settings(user.id)

    assert app_settings.news_agent_enabled is True
    assert app_settings.trade_journal_agent_enabled is False  # untouched, stays default
    assert app_settings.strategy_agent_enabled is True


async def test_agent_toggle_can_be_turned_back_off(db):
    user = await create_test_user(db, email="toggles-off@example.com")
    settings_service = SettingsService(db)

    await settings_service.update_app_settings(
        AppSettingsUpdate(trade_journal_agent_enabled=True), user.id
    )
    await settings_service.update_app_settings(
        AppSettingsUpdate(trade_journal_agent_enabled=False), user.id
    )
    app_settings = await settings_service.get_app_settings(user.id)

    assert app_settings.trade_journal_agent_enabled is False


async def test_agent_toggles_are_scoped_per_user(db):
    user_a = await create_test_user(db, email="toggles-a@example.com")
    user_b = await create_test_user(db, email="toggles-b@example.com")
    settings_service = SettingsService(db)

    await settings_service.update_app_settings(
        AppSettingsUpdate(news_agent_enabled=True), user_a.id
    )

    a_settings = await settings_service.get_app_settings(user_a.id)
    b_settings = await settings_service.get_app_settings(user_b.id)

    assert a_settings.news_agent_enabled is True
    assert b_settings.news_agent_enabled is False
