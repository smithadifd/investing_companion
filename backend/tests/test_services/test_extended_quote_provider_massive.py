"""Tests for the Massive-first extended-hours quote seam (BS10).

``get_extended_quote_provider`` (``app.services.data_providers.__init__``) is
the seam under test — its own docstring is the normative description. A
configured ``POLYGON_API_KEY`` promotes Massive to the front of the
extended-hours chain, with the existing selection
(``_get_base_extended_provider`` — Yahoo, or Schwab when its own separate
opt-in is on) wired in as the per-symbol fallback. Three paths, one test class
each, matching the BS10 contract's seam declaration exactly:

1. ``TestKeyedMassiveAvailable`` — keyed install + Massive answers -> a
   Massive-first, contractually labeled result.
2. ``TestKeyedMassiveUnavailable`` — keyed install + Massive errors/returns
   nothing -> falls through to the base provider (Yahoo by default).
3. ``TestKeylessUnchanged`` — no ``POLYGON_API_KEY`` -> byte-for-byte the
   pre-BS10 selection (the exact object ``_get_base_extended_provider``
   returns, unwrapped) — the most important negative path: nothing regresses
   for the common, unkeyed install.

Massive's own HTTP/parsing/session-derivation behaviour is NOT re-tested here
(see ``test_massive_provider.py``); these tests stub
``MassiveProvider.get_extended_quote`` directly so they pin only the
selector's *composition* behaviour, the same way the existing
``test_schwab_provider.py`` selector tests don't re-stub the Schwab HTTP
client either.

Never touches ``get_quote_provider``/``FailoverQuoteProvider`` (the real-time
chain) — that promotion is a separate, already-shipped seam this row does not
revisit.
"""

from app.core.config import settings
from app.services.data_providers import get_extended_quote_provider
from app.services.data_providers.base import ProviderError
from app.services.data_providers.massive import (
    MassiveExtendedQuoteProvider,
    MassiveProvider,
)
from app.services.data_providers.yahoo import YahooFinanceProvider


def _configure_massive(monkeypatch, key: str = "test-key") -> None:
    monkeypatch.setattr(settings, "POLYGON_API_KEY", key)


class TestKeyedMassiveAvailable:
    """(1) keyed install + Massive available -> Massive-first, labeled."""

    async def test_returns_a_massive_wrapper_around_the_base_provider(
        self, db, monkeypatch
    ):
        _configure_massive(monkeypatch)

        provider = await get_extended_quote_provider(db)

        assert isinstance(provider, MassiveExtendedQuoteProvider)
        assert isinstance(provider._massive, MassiveProvider)
        assert isinstance(provider._fallback, YahooFinanceProvider), (
            "Yahoo fallback intact — Schwab quotes are opt-in default OFF"
        )

    async def test_massive_answers_first_and_is_contractually_labeled(
        self, db, monkeypatch
    ):
        _configure_massive(monkeypatch)

        async def _fake_get_extended_quote(self, symbol):
            return {
                "price": 123.45,
                "change_percent": 1.23,
                "session": "pre",
                "source": "massive",
                "stale": True,
            }

        monkeypatch.setattr(
            MassiveProvider, "get_extended_quote", _fake_get_extended_quote
        )

        provider = await get_extended_quote_provider(db)
        quote = await provider.get_extended_quote("AAPL")

        assert quote["price"] == 123.45
        assert quote["session"] == "pre"
        # The contractual label (Q1: reuse IC#318's neutral delayed-label
        # convention verbatim — source/stale, not new copy).
        assert quote["source"] == "massive"
        assert quote["stale"] is True


class TestKeyedMassiveUnavailable:
    """(2) keyed install + Massive unavailable/errors -> Yahoo fallback."""

    async def test_a_raised_provider_error_falls_back_to_yahoo(self, db, monkeypatch):
        _configure_massive(monkeypatch)

        async def _boom(self, symbol):
            raise ProviderError("Massive rate limit reached (HTTP 429)")

        monkeypatch.setattr(MassiveProvider, "get_extended_quote", _boom)

        yahoo_quote = {"price": 99.0, "change_percent": -0.5, "session": "closed"}

        async def _fake_yahoo_extended_quote(self, symbol):
            return yahoo_quote

        monkeypatch.setattr(
            YahooFinanceProvider, "get_extended_quote", _fake_yahoo_extended_quote
        )

        provider = await get_extended_quote_provider(db)
        quote = await provider.get_extended_quote("AAPL")

        assert quote is yahoo_quote

    async def test_a_clean_none_from_massive_also_falls_back(self, db, monkeypatch):
        """Massive's own "can't quote this" is not a reason to skip the free
        chain's answer — it must route to the fallback exactly like an error."""
        _configure_massive(monkeypatch)

        async def _none(self, symbol):
            return None

        monkeypatch.setattr(MassiveProvider, "get_extended_quote", _none)

        yahoo_quote = {"price": 50.0, "change_percent": 0.0, "session": "regular"}

        async def _fake_yahoo_extended_quote(self, symbol):
            return yahoo_quote

        monkeypatch.setattr(
            YahooFinanceProvider, "get_extended_quote", _fake_yahoo_extended_quote
        )

        provider = await get_extended_quote_provider(db)
        quote = await provider.get_extended_quote("ZZZZ")

        assert quote is yahoo_quote


class TestKeylessUnchanged:
    """(3) no POLYGON_API_KEY -> the pre-BS10 selection, unwrapped.

    The negative path the contract calls out as most important: an unkeyed
    install (the common case) must see the exact same object type it saw
    before this row, not a wrapper around it.
    """

    async def test_returns_yahoo_directly_not_wrapped(self, db, monkeypatch):
        monkeypatch.setattr(settings, "POLYGON_API_KEY", "")

        provider = await get_extended_quote_provider(db)

        assert isinstance(provider, YahooFinanceProvider)
        assert not isinstance(provider, MassiveExtendedQuoteProvider)

    async def test_matches_the_base_selector_called_directly(self, db, monkeypatch):
        """Same object type get_extended_quote_provider always returned pre-
        BS10 — pinned via the private base-selector directly so a future edit
        to the Schwab/Yahoo half can't silently start wrapping it unkeyed."""
        from app.services.data_providers import _get_base_extended_provider

        monkeypatch.setattr(settings, "POLYGON_API_KEY", "")

        base = await _get_base_extended_provider(db)
        provider = await get_extended_quote_provider(db)

        assert type(provider) is type(base)
