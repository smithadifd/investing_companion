"""Tests for forex symbol normalization in the Yahoo provider (issue #49)."""

import pytest

from app.services.data_providers.yahoo import normalize_symbol


class TestNormalizeSymbol:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("USD/JPY", "USDJPY=X"),
            ("EUR/USD", "EURUSD=X"),
            ("EUR/JPY", "EURJPY=X"),
            ("USDJPY", "USDJPY=X"),
            ("CADUSD", "CADUSD=X"),
            ("JPY", "JPY=X"),
            ("EUR", "EUR=X"),
            ("usd/jpy", "USDJPY=X"),
        ],
    )
    def test_forex_formats_normalize(self, raw: str, expected: str):
        assert normalize_symbol(raw) == expected

    @pytest.mark.parametrize(
        "symbol",
        [
            "AAPL",        # plain equity
            "GOOGL",       # 5-letter equity
            "SRUUF",       # OTC 5-letter
            "BZ=F",        # futures
            "^VIX",        # index
            "BTC-USD",     # crypto
            "JPY=X",       # already Yahoo forex format
            "USDJPY=X",    # already Yahoo forex format
            "BRK-B",       # share class
        ],
    )
    def test_non_forex_passes_through(self, symbol: str):
        assert normalize_symbol(symbol) == symbol

    def test_bare_usd_passes_through(self):
        """A bare USD has no price; pass through so the lookup fails honestly."""
        assert normalize_symbol("USD") == "USD"

    def test_six_letter_equity_not_mangled(self):
        """Six letters that aren't two ISO currency codes stay untouched."""
        assert normalize_symbol("GOOGLE") == "GOOGLE"
