"""Tests for the Stooq no-key fallback provider (Queue S S4).

Pure parsing + symbol mapping tests, plus provider I/O with the CSV fetch
stubbed — no live network.
"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.services.data_providers.base import ProviderCapability
from app.services.data_providers.stooq import (
    StooqProvider,
    _to_stooq_symbol,
    parse_history_csv,
    quote_from_bars,
)

_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-06-05,100.0,102.0,99.5,101.0,1000000\n"
    "2026-06-08,101.0,103.0,100.5,102.5,1200000\n"
    "2026-06-09,102.5,105.0,102.0,104.0,1500000\n"
)


class TestSymbolMapping:
    def test_plain_us_ticker_gets_suffix(self):
        assert _to_stooq_symbol("AAPL") == "aapl.us"
        assert _to_stooq_symbol("spy") == "spy.us"

    def test_already_suffixed_passes_through(self):
        assert _to_stooq_symbol("aapl.us") == "aapl.us"

    def test_yahoo_only_notations_pass_through_lowercased(self):
        # Not well covered by Stooq -> honest miss, not a crash.
        assert _to_stooq_symbol("GC=F") == "gc=f"
        assert _to_stooq_symbol("^VIX") == "^vix"
        assert _to_stooq_symbol("BRK-B") == "brk-b"


class TestParseHistoryCsv:
    def test_parses_rows_oldest_to_newest(self):
        bars = parse_history_csv(_CSV)
        assert len(bars) == 3
        assert bars[0].close == Decimal("101.0")
        assert bars[-1].close == Decimal("104.0")
        assert bars[-1].volume == 1500000

    def test_no_data_body_returns_empty(self):
        assert parse_history_csv("") == []
        assert parse_history_csv("No data") == []
        # N/D placeholder rows are dropped.
        nd = "Date,Open,High,Low,Close,Volume\n2026-06-09,N/D,N/D,N/D,N/D,N/D\n"
        assert parse_history_csv(nd) == []


class TestQuoteFromBars:
    def test_change_computed_vs_prior_close(self):
        bars = parse_history_csv(_CSV)
        quote = quote_from_bars("AAPL", bars)
        assert quote is not None
        assert quote.price == Decimal("104.0")
        assert quote.previous_close == Decimal("102.5")
        assert quote.change == Decimal("1.5")  # 104.0 - 102.5
        assert quote.change_percent == pytest.approx(Decimal("1.463"), abs=Decimal("0.01"))
        assert quote.source == "stooq"

    def test_timestamp_is_latest_bar_not_fetch_time(self):
        from datetime import datetime

        quote = quote_from_bars("AAPL", parse_history_csv(_CSV))
        # "As of" reflects the real data age (latest bar), not now().
        assert quote.timestamp == datetime(2026, 6, 9)

    def test_zero_open_is_preserved_not_replaced_by_close(self):
        csv_zero = (
            "Date,Open,High,Low,Close,Volume\n"
            "2026-06-09,0.00,105.0,0.00,104.0,1500000\n"
        )
        bars = parse_history_csv(csv_zero)
        assert bars[0].open == Decimal("0.00")
        assert bars[0].low == Decimal("0.00")

    def test_single_bar_has_no_change(self):
        bars = parse_history_csv(
            "Date,Open,High,Low,Close,Volume\n2026-06-09,102.5,105.0,102.0,104.0,1500000\n"
        )
        quote = quote_from_bars("AAPL", bars)
        assert quote.change == Decimal("0")
        assert quote.previous_close is None

    def test_empty_bars_returns_none(self):
        assert quote_from_bars("AAPL", []) is None


class TestStooqProvider:
    def test_needs_no_api_key(self):
        # The whole point of Stooq: constructs with zero configuration.
        provider = StooqProvider()
        assert provider.supports(ProviderCapability.QUOTE)
        assert provider.supports(ProviderCapability.HISTORY)
        assert not provider.supports(ProviderCapability.FUNDAMENTALS)
        assert not provider.supports(ProviderCapability.SEARCH)

    async def test_get_quote_uses_recent_bars(self, monkeypatch):
        provider = StooqProvider()
        monkeypatch.setattr(provider, "_fetch_csv", AsyncMock(return_value=_CSV))
        quote = await provider.get_quote("AAPL")
        assert quote.price == Decimal("104.0")
        assert quote.source == "stooq"

    async def test_get_history_parses_csv(self, monkeypatch):
        provider = StooqProvider()
        monkeypatch.setattr(provider, "_fetch_csv", AsyncMock(return_value=_CSV))
        history = await provider.get_history("AAPL", period="1mo")
        assert len(history) == 3
        assert history[-1].close == Decimal("104.0")

    async def test_unknown_symbol_returns_none(self, monkeypatch):
        provider = StooqProvider()
        monkeypatch.setattr(provider, "_fetch_csv", AsyncMock(return_value="No data"))
        assert await provider.get_quote("ZZZZ") is None
