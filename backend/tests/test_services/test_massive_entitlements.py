"""Massive per-product entitlements — Wave AU row AU7 (issue #274).

Massive sells its surfaces as separate products, a key holds some and not
others, and the API offers no way to ask which. The app used to find out
reactively, one 403 at a time, and turned that 403 into ``{}`` — which is
indistinguishable from "this ticker has no data". An unowned product therefore
went quietly blank instead of falling through to Yahoo: a silent capability
loss dressed up as an empty result.

What is pinned here:

1. **Declaration** (``MASSIVE_ENTITLEMENTS``) — one place to read, one to
   change, with an empty value meaning "all" rather than "none" so a copied
   ``.env`` can't silently disable the provider.
2. **Routing** — an unentitled surface falls through to the next provider
   *exactly as a failure would*, and the caller gets that provider's data. This
   is the failover regression the issue asks for.
3. **Coverage** — the gate applies to every Massive call site, not just the one
   ``get_fundamentals`` used to carry.
4. **Health** — an unowned product must not spend the retry budget or trip the
   breaker, because the breaker is shared with the surfaces we *do* own.
5. **The 403 backstop** — declaration and reality drift; the runtime 403 still
   catches it, corrects the declared state, and logs loudly instead of
   absorbing it forever.

No network, no DB, no API key: every request is stubbed and the key throughout
is the literal string "test-key".
"""

import logging
from datetime import datetime
from decimal import Decimal

import pytest

from app.schemas.equity import (
    EquitySearchResult,
    FundamentalsResponse,
    OHLCVData,
    QuoteResponse,
)
from app.services.data_providers.base import (
    MarketDataProvider,
    ProviderCapability,
    ProviderError,
    ProviderUnentitledError,
)
from app.services.data_providers.massive import (
    MassiveEntitlements,
    MassiveProvider,
)
from app.services.data_providers.resilience import (
    FailoverQuoteProvider,
    ResilientProvider,
)

TEST_KEY = "test-key"

ALL_SURFACES = ["quote", "history", "fundamentals", "search"]

_SNAPSHOT = {
    "status": "OK",
    "ticker": {
        "ticker": "AAPL",
        "day": {"c": 120.42, "h": 120.53, "l": 118.81, "o": 119.62, "v": 28727868},
        "lastTrade": {"p": 120.47, "t": 1605195918306274000},
        "prevDay": {"c": 119.49},
        "updated": 1605195918306274000,
    },
}

_AGGREGATES = {
    "status": "OK",
    "results": [
        {"t": 1704171600000, "o": 100.0, "h": 105.0, "l": 99.0, "c": 104.0, "v": 1500000}
    ],
}

_RATIOS = {
    "status": "OK",
    "results": [{"ticker": "AAPL", "market_cap": 3050000000000, "price_to_earnings": 31.2}],
}

_TICKER_SEARCH = {
    "status": "OK",
    "results": [
        {"ticker": "AAPL", "name": "Apple Inc.", "primary_exchange": "XNAS", "type": "CS"}
    ],
}

#: capability -> (method name, args, stub payload for the entitled case)
_CALL_SITES = {
    ProviderCapability.QUOTE: ("get_quote", ("AAPL",), _SNAPSHOT),
    ProviderCapability.HISTORY: ("get_history", ("AAPL",), _AGGREGATES),
    ProviderCapability.FUNDAMENTALS: ("get_fundamentals", ("AAPL",), _RATIOS),
    ProviderCapability.SEARCH: ("search", ("apple",), _TICKER_SEARCH),
}


class _StubResponse:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _HttpSpy:
    """Counts requests so "never left the process" is directly assertable."""

    def __init__(self):
        self.calls: list[str] = []

    @property
    def count(self) -> int:
        return len(self.calls)


def _stub_http(monkeypatch, response: _StubResponse) -> _HttpSpy:
    from app.services.data_providers import massive as massive_module

    spy = _HttpSpy()

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None, headers=None):
            spy.calls.append(url)
            return response

    monkeypatch.setattr(massive_module.httpx, "AsyncClient", _Client)
    return spy


def _provider(entitled, **kwargs) -> MassiveProvider:
    """A Massive provider entitled to exactly ``entitled``."""
    return MassiveProvider(
        api_key=TEST_KEY,
        entitlements=MassiveEntitlements([c.value for c in entitled]),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# The declaration itself
# ---------------------------------------------------------------------------


class TestDeclaration:
    """``MASSIVE_ENTITLEMENTS``: one place to read, one place to change."""

    def test_undeclared_entitles_everything(self):
        """``None`` = "nobody declared anything" = the historical behaviour.

        Discovering reality from 403s is worse than declaring it, but it is
        strictly better than a version bump silently switching every surface
        off for installs that never set the new variable.
        """
        assert MassiveEntitlements().declared == frozenset(ProviderCapability)

    def test_names_are_case_and_whitespace_insensitive(self):
        entitlements = MassiveEntitlements([" History ", "FUNDAMENTALS"])
        assert entitlements.declared == {
            ProviderCapability.HISTORY,
            ProviderCapability.FUNDAMENTALS,
        }

    def test_an_explicit_empty_declaration_entitles_nothing(self):
        assert MassiveEntitlements([]).declared == frozenset()

    def test_an_unrecognised_name_is_loud_and_not_entitled(self, caplog):
        """A typo must never fail *quiet*.

        Silently accepting ``fundemantals`` would route fundamentals away from
        Massive forever with nothing in the logs to explain it — the exact
        invisible failure this declaration exists to prevent.
        """
        with caplog.at_level(logging.ERROR):
            entitlements = MassiveEntitlements(["history", "fundemantals"])

        assert entitlements.declared == {ProviderCapability.HISTORY}
        assert "MASSIVE_ENTITLEMENTS" in caplog.text
        assert "fundemantals" in caplog.text

    def test_it_reads_the_one_config_variable(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "MASSIVE_ENTITLEMENTS", ["history", "search"])
        entitlements = MassiveEntitlements.from_settings()
        assert entitlements.declared == {
            ProviderCapability.HISTORY,
            ProviderCapability.SEARCH,
        }

    def test_the_provider_defaults_to_the_configured_declaration(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "MASSIVE_ENTITLEMENTS", ["history"])
        provider = MassiveProvider(api_key=TEST_KEY)
        assert provider.entitlements.declared == {ProviderCapability.HISTORY}


class TestConfigParsing:
    """The env var reaches ``Settings`` in the shape the provider expects."""

    def test_comma_separated_string_is_split_and_normalised(self):
        from app.core.config import Settings

        parsed = Settings(MASSIVE_ENTITLEMENTS="History, FUNDAMENTALS ,search")
        assert parsed.MASSIVE_ENTITLEMENTS == ["history", "fundamentals", "search"]

    def test_the_default_is_every_surface(self):
        from app.core.config import Settings

        assert sorted(Settings().MASSIVE_ENTITLEMENTS) == sorted(ALL_SURFACES)

    @pytest.mark.parametrize("blank", ["", "   ", ",", []])
    def test_a_blank_value_means_all_not_none(self, blank):
        """The footgun guard.

        ``MASSIVE_ENTITLEMENTS=`` is what a copied ``.env.example`` and a
        ``${MASSIVE_ENTITLEMENTS:-}`` compose line both produce. Reading that as
        "nothing is entitled" would silently switch off a provider the owner is
        paying for. "Nothing" is spelled by clearing ``POLYGON_API_KEY``.
        """
        from app.core.config import Settings

        parsed = Settings(MASSIVE_ENTITLEMENTS=blank)
        assert sorted(parsed.MASSIVE_ENTITLEMENTS) == sorted(ALL_SURFACES)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("quote,history", ["history", "quote"]),
            (" QUOTE , History ", ["history", "quote"]),
            ("", ALL_SURFACES),
            ("   ", ALL_SURFACES),
            (",,,", ALL_SURFACES),
        ],
    )
    def test_the_real_environment_path_parses(self, monkeypatch, raw, expected):
        """The production path, not just the constructor.

        Every deployment sets this through the *environment* — the compose
        files pass ``MASSIVE_ENTITLEMENTS=${MASSIVE_ENTITLEMENTS:-}`` — and a
        list-typed pydantic-settings field reached from an env var goes through
        complex-value decoding before any validator runs. A comma-separated
        value is not JSON, so the footgun guard has to hold on this path
        specifically: if it ever stopped, the blank compose line would either
        fail the app's boot or silently entitle nothing, and the constructor
        tests above would still be green.
        """
        from app.core.config import Settings

        monkeypatch.setenv("MASSIVE_ENTITLEMENTS", raw)
        parsed = Settings(_env_file=None)
        assert sorted(parsed.MASSIVE_ENTITLEMENTS) == sorted(expected)

    def test_an_unset_environment_entitles_everything(self, monkeypatch):
        """An install that never heard of this variable keeps working."""
        from app.core.config import Settings

        monkeypatch.delenv("MASSIVE_ENTITLEMENTS", raising=False)
        parsed = Settings(_env_file=None)
        assert sorted(parsed.MASSIVE_ENTITLEMENTS) == sorted(ALL_SURFACES)


# ---------------------------------------------------------------------------
# The gate — every call site, not just fundamentals
# ---------------------------------------------------------------------------


class TestEveryCallSiteIsGated:
    """Coverage used to stop at ``get_fundamentals``; it now covers all four."""

    @pytest.mark.parametrize("capability", list(ProviderCapability))
    async def test_an_unentitled_surface_never_leaves_the_process(
        self, monkeypatch, capability
    ):
        method_name, args, payload = _CALL_SITES[capability]
        spy = _stub_http(monkeypatch, _StubResponse(200, payload))
        provider = _provider(set(ProviderCapability) - {capability})

        with pytest.raises(ProviderUnentitledError):
            await getattr(provider, method_name)(*args)

        assert spy.count == 0, "an undeclared surface still made a request"

    @pytest.mark.parametrize("capability", list(ProviderCapability))
    async def test_an_entitled_surface_is_called_normally(self, monkeypatch, capability):
        """The gate must not be a blanket off-switch: what is declared still works."""
        method_name, args, payload = _CALL_SITES[capability]
        spy = _stub_http(monkeypatch, _StubResponse(200, payload))
        provider = _provider({capability})

        result = await getattr(provider, method_name)(*args)

        assert spy.count == 1
        assert result not in (None, [])

    async def test_one_unentitled_surface_does_not_disable_the_others(self, monkeypatch):
        """The original reason 403 was swallowed: don't lose the whole provider."""
        _stub_http(monkeypatch, _StubResponse(200, _AGGREGATES))
        provider = _provider(set(ProviderCapability) - {ProviderCapability.FUNDAMENTALS})

        assert await provider.get_history("AAPL") != []
        with pytest.raises(ProviderUnentitledError):
            await provider.get_fundamentals("AAPL")

    def test_capabilities_still_advertise_what_the_adapter_implements(self):
        """Entitlement is a routing fact, not a code fact.

        ``capabilities`` describes what this adapter can talk to; narrowing it
        per-plan would make a provider's advertised shape depend on a billing
        detail and would be snapshotted stale by every wrapper that copies it.
        """
        provider = _provider({ProviderCapability.HISTORY})
        assert provider.capabilities == frozenset(ProviderCapability)


# ---------------------------------------------------------------------------
# Health: an unowned product is not an unhealthy provider
# ---------------------------------------------------------------------------


class TestUnentitledIsNotAHealthEvent:
    async def test_it_is_not_retried_and_does_not_trip_the_breaker(self, monkeypatch):
        """Retrying cannot make a plan include a product.

        And because the breaker is shared across a provider's capabilities,
        counting this would take history and search down every time a
        fundamentals lookup ran — the very outcome the 403-to-empty handling
        was written to avoid.
        """
        spy = _stub_http(monkeypatch, _StubResponse(200, _RATIOS))
        wrapped = ResilientProvider(
            _provider({ProviderCapability.HISTORY}), max_retries=2
        )

        with pytest.raises(ProviderUnentitledError):
            await wrapped.get_fundamentals("AAPL")

        assert spy.count == 0
        assert wrapped.breaker.failure_count == 0
        assert wrapped.breaker.state.value == "closed"

    async def test_a_real_failure_still_counts(self, monkeypatch):
        """The carve-out is narrow: a 429 on an entitled surface is still health."""
        _stub_http(monkeypatch, _StubResponse(429, {"status": "ERROR"}))
        wrapped = ResilientProvider(
            _provider({ProviderCapability.HISTORY}), max_retries=0
        )

        with pytest.raises(ProviderError):
            await wrapped.get_history("AAPL")

        assert wrapped.breaker.failure_count == 1


# ---------------------------------------------------------------------------
# THE failover regression: unentitled routes to the next provider
# ---------------------------------------------------------------------------


def _quote(source: str, price: str) -> QuoteResponse:
    return QuoteResponse(
        symbol="AAPL",
        price=Decimal(price),
        change=Decimal("1"),
        change_percent=Decimal("1"),
        open=Decimal("99"),
        high=Decimal("101"),
        low=Decimal("98"),
        previous_close=Decimal("99"),
        volume=1000,
        timestamp=datetime(2026, 8, 14, 12, 0, 0),
        source=source,
    )


class _StubFallback(MarketDataProvider):
    """Stands in for Yahoo: answers every capability with recognisable data."""

    name = "yahoo"
    capabilities = frozenset(ProviderCapability)

    def __init__(self):
        self.calls: list[str] = []

    async def get_quote(self, symbol: str) -> QuoteResponse | None:
        self.calls.append("get_quote")
        return _quote("yahoo", "100")

    async def get_history(self, symbol, period="1y", interval="1d"):
        self.calls.append("get_history")
        return [
            OHLCVData(
                timestamp=datetime(2026, 8, 13),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10.5"),
                volume=42,
            )
        ]

    async def get_fundamentals(self, symbol: str) -> FundamentalsResponse | None:
        self.calls.append("get_fundamentals")
        return FundamentalsResponse(pe_ratio=Decimal("21.5"))

    async def search(self, query: str, limit: int = 20):
        self.calls.append("search")
        return [EquitySearchResult(symbol="AAPL", name="Apple Inc.")]


class TestUnentitledRoutesToTheNextProvider:
    """The outcome the issue asks for, asserted end to end.

    Massive is placed **first** in each chain on purpose. In the shipped chain
    it is appended last, so a fall-through there is invisible — Yahoo answered
    before Massive was ever consulted. Putting it at the head is the only way to
    prove the routing itself works, and it is also the configuration a future
    reorder (or a Massive-first chain built by another caller) would produce.
    """

    @pytest.mark.parametrize(
        "capability,method,expected_call",
        [
            (ProviderCapability.FUNDAMENTALS, "get_fundamentals", "get_fundamentals"),
            (ProviderCapability.HISTORY, "get_history", "get_history"),
            (ProviderCapability.SEARCH, "search", "search"),
            (ProviderCapability.QUOTE, "get_quote", "get_quote"),
        ],
    )
    async def test_the_next_provider_answers(
        self, monkeypatch, capability, method, expected_call
    ):
        spy = _stub_http(monkeypatch, _StubResponse(200, _CALL_SITES[capability][2]))
        fallback = _StubFallback()
        massive = _provider(set(ProviderCapability) - {capability})
        chain = FailoverQuoteProvider([ResilientProvider(massive), fallback])

        result = await getattr(chain, method)("AAPL")

        assert spy.count == 0, "the unentitled surface was still requested"
        assert expected_call in fallback.calls, "the chain did not fall through"
        assert result not in (None, [], {}), "an unentitled surface returned an empty"

    async def test_fundamentals_are_the_fallbacks_not_an_empty_card(self, monkeypatch):
        """The concrete complaint from the issue: a blank panel that looked like
        a thin ticker when Yahoo could have answered."""
        _stub_http(monkeypatch, _StubResponse(200, _RATIOS))
        fallback = _StubFallback()
        chain = FailoverQuoteProvider(
            [
                ResilientProvider(
                    _provider(set(ProviderCapability) - {ProviderCapability.FUNDAMENTALS})
                ),
                fallback,
            ]
        )

        fundamentals = await chain.get_fundamentals("AAPL")

        assert fundamentals is not None
        assert fundamentals.pe_ratio == Decimal("21.5")

    async def test_an_entitled_surface_still_wins_from_the_head_of_the_chain(
        self, monkeypatch
    ):
        """The gate routes past what we don't own — not past what we do."""
        _stub_http(monkeypatch, _StubResponse(200, _RATIOS))
        fallback = _StubFallback()
        chain = FailoverQuoteProvider(
            [
                ResilientProvider(_provider({ProviderCapability.FUNDAMENTALS})),
                fallback,
            ]
        )

        fundamentals = await chain.get_fundamentals("AAPL")

        assert fundamentals.market_cap == 3050000000000
        assert fallback.calls == [], "the entitled provider was skipped"


# ---------------------------------------------------------------------------
# The 403 backstop: declaration and reality drift
# ---------------------------------------------------------------------------


class TestDriftBackstop:
    """A declaration can be wrong — a plan change, a rebrand, a mis-set flag.

    The runtime 403 stays as the safety net, but it now *corrects* the declared
    state and says so loudly instead of absorbing the 403 into an empty forever.
    """

    async def test_a_403_on_a_declared_surface_is_loud(self, monkeypatch, caplog):
        _stub_http(monkeypatch, _StubResponse(403, {"status": "NOT_AUTHORIZED"}))
        provider = _provider(set(ProviderCapability))

        with caplog.at_level(logging.ERROR):
            with pytest.raises(ProviderUnentitledError):
                await provider.get_fundamentals("AAPL")

        assert "MASSIVE ENTITLEMENT DRIFT" in caplog.text
        # The message has to carry the fix, not just the complaint.
        assert "MASSIVE_ENTITLEMENTS=" in caplog.text
        assert "fundamentals" in caplog.text

    async def test_the_correction_sticks_and_stops_costing_a_round_trip(
        self, monkeypatch
    ):
        spy = _stub_http(monkeypatch, _StubResponse(403, {"status": "NOT_AUTHORIZED"}))
        provider = _provider(set(ProviderCapability))

        with pytest.raises(ProviderUnentitledError):
            await provider.get_fundamentals("AAPL")
        assert spy.count == 1

        with pytest.raises(ProviderUnentitledError):
            await provider.get_fundamentals("AAPL")
        assert spy.count == 1, "the corrected surface was requested again"

        assert provider.entitlements.revoked == {ProviderCapability.FUNDAMENTALS}
        assert ProviderCapability.FUNDAMENTALS not in provider.entitlements.effective
        # Declared state is preserved so the log can name what config still claims.
        assert ProviderCapability.FUNDAMENTALS in provider.entitlements.declared

    async def test_the_correction_is_scoped_to_the_one_surface(self, monkeypatch):
        provider = _provider(set(ProviderCapability))
        _stub_http(monkeypatch, _StubResponse(403, {"status": "NOT_AUTHORIZED"}))
        with pytest.raises(ProviderUnentitledError):
            await provider.get_fundamentals("AAPL")

        _stub_http(monkeypatch, _StubResponse(200, _AGGREGATES))
        assert await provider.get_history("AAPL") != []

    async def test_it_does_not_repeat_the_loud_log_for_a_known_gap(
        self, monkeypatch, caplog
    ):
        """Loud once, per drift. A per-request ERROR would train the owner to
        ignore the channel that is supposed to tell him the plan changed."""
        _stub_http(monkeypatch, _StubResponse(403, {"status": "NOT_AUTHORIZED"}))
        entitlements = MassiveEntitlements(ALL_SURFACES)

        with caplog.at_level(logging.ERROR):
            assert entitlements.revoke(ProviderCapability.FUNDAMENTALS) is True
            assert entitlements.revoke(ProviderCapability.FUNDAMENTALS) is False

        assert caplog.text.count("MASSIVE ENTITLEMENT DRIFT") == 1

    async def test_the_chain_routes_on_the_drift_too(self, monkeypatch):
        """The backstop has to produce the same routing as the declaration —
        otherwise a wrong declaration is still a silent blank panel."""
        _stub_http(monkeypatch, _StubResponse(403, {"status": "NOT_AUTHORIZED"}))
        fallback = _StubFallback()
        chain = FailoverQuoteProvider(
            [ResilientProvider(_provider(set(ProviderCapability))), fallback]
        )

        fundamentals = await chain.get_fundamentals("AAPL")

        assert fundamentals is not None
        assert fundamentals.pe_ratio == Decimal("21.5")

    async def test_drift_does_not_trip_the_breaker(self, monkeypatch):
        _stub_http(monkeypatch, _StubResponse(403, {"status": "NOT_AUTHORIZED"}))
        wrapped = ResilientProvider(_provider(set(ProviderCapability)), max_retries=2)

        with pytest.raises(ProviderUnentitledError):
            await wrapped.get_fundamentals("AAPL")

        assert wrapped.breaker.failure_count == 0

    def test_the_declared_state_is_inspectable_not_only_loggable(self):
        entitlements = MassiveEntitlements(ALL_SURFACES)
        assert entitlements.describe() == "fundamentals,history,quote,search"
        entitlements.revoke(ProviderCapability.FUNDAMENTALS)
        assert "403-corrected: fundamentals" in entitlements.describe()

    def test_reverse_drift_is_out_of_reach_by_construction(self):
        """Documented limitation, pinned so it can't be forgotten.

        A surface declared unentitled is never called, so a plan *upgrade* that
        grants it back cannot be observed here — re-enabling is a config edit.
        The alternative would be speculatively calling endpoints we were just
        told we don't own, which is how the reactive-discovery cost showed up
        in the first place.
        """
        entitlements = MassiveEntitlements(["history"])
        assert entitlements.allows(ProviderCapability.FUNDAMENTALS) is False
        assert entitlements.revoked == frozenset()
