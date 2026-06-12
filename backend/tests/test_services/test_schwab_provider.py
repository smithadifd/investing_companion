"""Tests for the Schwab extended-hours quote provider (Phase F, PR-B)."""

import json
import time
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.services.cache import cache_service
from app.services.data_providers.schwab import (
    SchwabProvider,
    _current_extended_session,
    _parse_schwab_quote,
    parse_wrapped_token,
    token_age_days,
    token_is_expired,
)

_ET = ZoneInfo("America/New_York")


def _et(hour: int, minute: int = 0, day: int = 9) -> datetime:
    """An ET datetime on a weekday (2026-06-09 is a Tuesday)."""
    return datetime(2026, 6, 9 + (day - 9), hour, minute, tzinfo=_ET)


def _ms(dt: datetime) -> float:
    return dt.timestamp() * 1000


# ---------------------------------------------------------------------------
# Session derivation from the ET clock
# ---------------------------------------------------------------------------
class TestCurrentExtendedSession:
    def test_weekday_windows(self):
        assert _current_extended_session(_et(3, 59)) == "closed"
        assert _current_extended_session(_et(4, 0)) == "pre"
        assert _current_extended_session(_et(9, 29)) == "pre"
        assert _current_extended_session(_et(9, 30)) == "regular"
        assert _current_extended_session(_et(15, 59)) == "regular"
        assert _current_extended_session(_et(16, 0)) == "post"
        assert _current_extended_session(_et(19, 59)) == "post"
        assert _current_extended_session(_et(20, 0)) == "closed"

    def test_weekend_is_closed(self):
        saturday = datetime(2026, 6, 13, 10, 0, tzinfo=_ET)
        assert _current_extended_session(saturday) == "closed"


# ---------------------------------------------------------------------------
# Quote parsing / honesty rules
# ---------------------------------------------------------------------------
def _schwab_data(**overrides) -> dict:
    data = {
        "quote": {
            "lastPrice": 104.0,
            "closePrice": 100.0,
            "netPercentChange": 4.0,
            "tradeTime": None,
        },
        "regular": {
            "regularMarketLastPrice": 100.0,
            "regularMarketPercentChange": -1.5,
        },
    }
    for section, values in overrides.items():
        data[section].update(values)
    return data


class TestParseSchwabQuote:
    def test_pre_session_with_trade_evidence(self):
        now = _et(8, 0)
        data = _schwab_data(quote={"tradeTime": _ms(_et(7, 55))})
        quote = _parse_schwab_quote(data, "pre", now)
        assert quote == {"price": 104.0, "change_percent": 4.0, "session": "pre"}

    def test_pre_session_without_trade_evidence_degrades_to_closed(self):
        """No pre-market trade today: yesterday's move must not masquerade
        as a pre-market move."""
        now = _et(8, 0)
        quote = _parse_schwab_quote(_schwab_data(), "pre", now)
        assert quote["session"] == "closed"
        assert quote["price"] == 100.0
        assert quote["change_percent"] == -1.5

    def test_pre_session_with_stale_trade_from_yesterday_degrades(self):
        now = _et(8, 0)
        yesterday_post = _ms(_et(19, 0) .replace(day=8))
        data = _schwab_data(quote={"tradeTime": yesterday_post})
        quote = _parse_schwab_quote(data, "pre", now)
        assert quote["session"] == "closed"

    def test_post_session_uses_postmarket_percent_when_present(self):
        now = _et(17, 0)
        data = _schwab_data(
            quote={"tradeTime": _ms(_et(16, 45)), "postMarketPercentChange": -7.0,
                   "lastPrice": 93.0}
        )
        quote = _parse_schwab_quote(data, "post", now)
        assert quote == {"price": 93.0, "change_percent": -7.0, "session": "post"}

    def test_post_session_percent_computed_vs_regular_close(self):
        """Post-market change is vs today's regular close, not yesterday's."""
        now = _et(17, 0)
        data = _schwab_data(quote={"tradeTime": _ms(_et(16, 45)), "lastPrice": 97.0})
        quote = _parse_schwab_quote(data, "post", now)
        assert quote["session"] == "post"
        assert quote["price"] == 97.0
        assert quote["change_percent"] == pytest.approx(-3.0)

    def test_regular_session_uses_net_percent_change(self):
        quote = _parse_schwab_quote(_schwab_data(), "regular", _et(12, 0))
        assert quote == {"price": 104.0, "change_percent": 4.0, "session": "regular"}

    def test_closed_falls_back_to_regular_session_change(self):
        quote = _parse_schwab_quote(_schwab_data(), "closed", _et(22, 0))
        assert quote == {"price": 100.0, "change_percent": -1.5, "session": "closed"}

    def test_no_price_data_returns_none(self):
        assert _parse_schwab_quote({"quote": {}, "regular": {}}, "regular", _et(12, 0)) is None


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------
class TestTokenHelpers:
    def test_parse_wrapped_token_roundtrip(self):
        wrapped = {"creation_timestamp": 123, "token": {"access_token": "x"}}
        assert parse_wrapped_token(json.dumps(wrapped)) == wrapped

    def test_parse_wrapped_token_rejects_garbage(self):
        assert parse_wrapped_token(None) is None
        assert parse_wrapped_token("") is None
        assert parse_wrapped_token("not json") is None
        assert parse_wrapped_token(json.dumps({"no_token_key": 1})) is None

    def test_token_age_and_expiry(self):
        fresh = {"creation_timestamp": time.time() - 3600, "token": {}}
        old = {"creation_timestamp": time.time() - 8 * 86400, "token": {}}
        assert token_age_days(fresh) == pytest.approx(1 / 24, abs=0.01)
        assert not token_is_expired(fresh)
        assert token_is_expired(old)
        assert token_is_expired({"token": {}})  # missing timestamp = expired


# ---------------------------------------------------------------------------
# Provider routing + fallback
# ---------------------------------------------------------------------------
def _fresh_wrapped_token() -> dict:
    return {"creation_timestamp": int(time.time()), "token": {"access_token": "x"}}


def _provider(fallback) -> SchwabProvider:
    return SchwabProvider(
        db=None, user_id=None, wrapped_token=_fresh_wrapped_token(), fallback=fallback
    )


class _StubResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def no_cache(monkeypatch):
    monkeypatch.setattr(cache_service, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(cache_service, "set", AsyncMock())


class TestSchwabProviderRouting:
    async def test_non_equity_symbols_delegate_to_fallback(self, no_cache):
        fallback = AsyncMock()
        fallback.get_extended_quote.return_value = {
            "price": 1.0, "change_percent": 0.5, "session": "regular",
        }
        provider = _provider(fallback)

        for symbol in ("GC=F", "^VIX", "JPY=X", "DX-Y.NYB", "BRK-B"):
            quote = await provider.get_extended_quote(symbol)
            assert quote["change_percent"] == 0.5
        assert fallback.get_extended_quote.await_count == 5

    async def test_equity_symbol_uses_schwab(self, no_cache):
        fallback = AsyncMock()
        provider = _provider(fallback)
        provider._client = AsyncMock()
        provider._client.get_quote.return_value = _StubResponse(
            200, {"AAPL": _schwab_data()}
        )

        quote = await provider.get_extended_quote("AAPL")
        # Deterministic regardless of wall clock: the stub has no extended
        # trade evidence, so pre/post degrade to closed; regular/closed use
        # their own fields.
        assert quote["session"] in ("regular", "closed")
        assert quote["price"] in (104.0, 100.0)
        fallback.get_extended_quote.assert_not_awaited()

    async def test_http_error_falls_back(self, no_cache):
        fallback = AsyncMock()
        fallback.get_extended_quote.return_value = {"price": 2.0}
        provider = _provider(fallback)
        provider._client = AsyncMock()
        provider._client.get_quote.return_value = _StubResponse(401, {})

        quote = await provider.get_extended_quote("AAPL")
        assert quote == {"price": 2.0}
        fallback.get_extended_quote.assert_awaited_once_with("AAPL")

    async def test_exception_falls_back(self, no_cache):
        fallback = AsyncMock()
        fallback.get_extended_quote.return_value = {"price": 3.0}
        provider = _provider(fallback)
        provider._client = AsyncMock()
        provider._client.get_quote.side_effect = RuntimeError("schwab down")

        quote = await provider.get_extended_quote("AAPL")
        assert quote == {"price": 3.0}

    async def test_missing_symbol_in_payload_falls_back(self, no_cache):
        fallback = AsyncMock()
        fallback.get_extended_quote.return_value = {"price": 4.0}
        provider = _provider(fallback)
        provider._client = AsyncMock()
        provider._client.get_quote.return_value = _StubResponse(200, {})

        quote = await provider.get_extended_quote("AAPL")
        assert quote == {"price": 4.0}


class TestSchwabTokenRefreshPersistence:
    async def test_refreshed_token_is_persisted(self, db, test_user, no_cache):
        """When schwab-py refreshes the access token mid-call, the new token
        must be written back to the encrypted setting."""
        from app.services.settings import SettingsService

        provider = SchwabProvider(
            db=db,
            user_id=test_user.id,
            wrapped_token=_fresh_wrapped_token(),
            fallback=AsyncMock(),
        )
        refreshed = {"creation_timestamp": 1, "token": {"access_token": "new"}}

        client = AsyncMock()

        async def _get_quote(symbol):
            # Simulate authlib refreshing the token during the request
            provider._token_write(refreshed)
            return _StubResponse(200, {"AAPL": _schwab_data()})

        client.get_quote.side_effect = _get_quote
        provider._client = client

        await provider.get_extended_quote("AAPL")

        service = SettingsService(db)
        stored = await service.get_setting(SettingsService.SCHWAB_TOKEN, test_user.id)
        assert json.loads(stored) == refreshed
        assert provider._wrapped_token == refreshed


# ---------------------------------------------------------------------------
# Provider selection (Schwab when connected, else Yahoo)
# ---------------------------------------------------------------------------
class TestGetExtendedQuoteProvider:
    async def test_unconfigured_returns_yahoo(self, db, monkeypatch):
        from app.core.config import settings
        from app.services.data_providers import get_extended_quote_provider
        from app.services.data_providers.yahoo import YahooFinanceProvider

        monkeypatch.setattr(settings, "SCHWAB_APP_KEY", "")
        provider = await get_extended_quote_provider(db)
        assert isinstance(provider, YahooFinanceProvider)

    async def test_configured_without_token_returns_yahoo(self, db, monkeypatch):
        from app.core.config import settings
        from app.services.data_providers import get_extended_quote_provider
        from app.services.data_providers.yahoo import YahooFinanceProvider

        monkeypatch.setattr(settings, "SCHWAB_APP_KEY", "k")
        monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "s")
        monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://x/cb")
        provider = await get_extended_quote_provider(db)
        assert isinstance(provider, YahooFinanceProvider)

    async def test_configured_with_fresh_token_returns_schwab(
        self, db, test_user, monkeypatch
    ):
        from app.core.config import settings
        from app.services.data_providers import get_extended_quote_provider
        from app.services.settings import SettingsService

        monkeypatch.setattr(settings, "SCHWAB_APP_KEY", "k")
        monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "s")
        monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://x/cb")

        service = SettingsService(db)
        await service.set_setting(
            SettingsService.SCHWAB_TOKEN,
            json.dumps(_fresh_wrapped_token()),
            test_user.id,
        )

        provider = await get_extended_quote_provider(db)
        assert isinstance(provider, SchwabProvider)
        assert provider.user_id == test_user.id

    async def test_expired_token_falls_back_to_yahoo(
        self, db, test_user, monkeypatch
    ):
        from app.core.config import settings
        from app.services.data_providers import get_extended_quote_provider
        from app.services.data_providers.yahoo import YahooFinanceProvider
        from app.services.settings import SettingsService

        monkeypatch.setattr(settings, "SCHWAB_APP_KEY", "k")
        monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "s")
        monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://x/cb")

        service = SettingsService(db)
        await service.set_setting(
            SettingsService.SCHWAB_TOKEN,
            json.dumps(
                {"creation_timestamp": int(time.time()) - 8 * 86400, "token": {}}
            ),
            test_user.id,
        )

        provider = await get_extended_quote_provider(db)
        assert isinstance(provider, YahooFinanceProvider)


class TestSchwabProviderClose:
    async def test_aclose_closes_client_session(self, no_cache):
        provider = _provider(AsyncMock())
        client = AsyncMock()
        provider._client = client

        await provider.aclose()
        client.close_async_session.assert_awaited_once()
        assert provider._client is None

    async def test_aclose_without_client_is_noop(self):
        provider = _provider(AsyncMock())
        await provider.aclose()  # must not raise
