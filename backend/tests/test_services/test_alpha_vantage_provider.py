"""Tests for the key-gated Alpha Vantage fallback provider (Queue S S4)."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.services.data_providers.base import ProviderError
from app.services.data_providers.alpha_vantage import (
    AlphaVantageProvider,
    is_alpha_vantage_configured,
    parse_global_quote,
)

_GLOBAL_QUOTE = {
    "Global Quote": {
        "01. symbol": "AAPL",
        "02. open": "100.0",
        "03. high": "105.0",
        "04. low": "99.0",
        "05. price": "104.0",
        "06. volume": "1500000",
        "08. previous close": "102.5",
        "09. change": "1.5",
        "10. change percent": "1.4634%",
    }
}


class TestKeyGating:
    def test_configured_reflects_settings(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "")
        assert is_alpha_vantage_configured() is False
        monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "demo-key")
        assert is_alpha_vantage_configured() is True

    def test_inert_without_key(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "")
        with pytest.raises(ProviderError):
            AlphaVantageProvider()

    def test_constructs_with_key(self):
        provider = AlphaVantageProvider(api_key="demo-key")
        assert provider.name == "alpha_vantage"


class TestParseGlobalQuote:
    def test_parses_fields(self):
        quote = parse_global_quote("AAPL", _GLOBAL_QUOTE)
        assert quote is not None
        assert quote.price == Decimal("104.0")
        assert quote.previous_close == Decimal("102.5")
        assert quote.change == Decimal("1.5")
        assert quote.change_percent == Decimal("1.4634")  # trailing % stripped
        assert quote.volume == 1500000
        assert quote.source == "alpha_vantage"

    def test_empty_payload_returns_none(self):
        assert parse_global_quote("AAPL", {}) is None
        assert parse_global_quote("AAPL", {"Global Quote": {}}) is None


class TestGetQuote:
    async def test_get_quote_maps_payload(self):
        provider = AlphaVantageProvider(api_key="demo-key")
        provider._fetch_json = AsyncMock(return_value=_GLOBAL_QUOTE)
        quote = await provider.get_quote("AAPL")
        assert quote.price == Decimal("104.0")

    async def test_rate_limit_note_is_provider_error(self, monkeypatch):
        """A free-tier rate-limit 'Note' payload must fail over, not parse."""
        from app.services.data_providers import alpha_vantage as av

        provider = AlphaVantageProvider(api_key="demo-key")

        class _Resp:
            status_code = 200

            def json(self):
                return {"Note": "call frequency limit reached"}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, *args, **kwargs):
                return _Resp()

        monkeypatch.setattr(av.httpx, "AsyncClient", lambda *a, **k: _Client())
        with pytest.raises(ProviderError):
            await provider.get_quote("AAPL")
