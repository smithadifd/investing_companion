"""Tests for the Massive (Polygon.io) provider — Wave AT row AT7.

Two things are under test here:

1. The adapter itself: key gating, HTTP status policy, and the payload parsers
   for aggregates / snapshot / ratios / ticker search.
2. **The chain-position regression** (``TestDelayedQuoteChainPosition``). Massive's
   Starter plan is 15-minute delayed, so it must never be consulted for a quote
   ahead of a live source. That is a correctness constraint, not a preference —
   getting it backwards silently serves a 15-minute-old price as if it were
   current — so it is pinned from several angles, including the case where a
   future edit mis-orders the chain by hand.

No network, no DB, and no API key: every request is stubbed and the key used
throughout is the literal string "test-key".
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app.schemas.equity import OHLCVData, QuoteResponse
from app.services.data_providers.base import (
    MarketDataProvider,
    ProviderCapability,
    ProviderError,
)
from app.services.data_providers.massive import (
    MassiveProvider,
    is_massive_configured,
    parse_aggregates,
    parse_ratios,
    parse_snapshot,
    parse_ticker_search,
)
from app.services.data_providers.resilience import (
    FailoverQuoteProvider,
    ResilientProvider,
    _stamp_stale,
)

# A fake key. Never a real credential — the provider is never given one in tests.
TEST_KEY = "test-key"

_SNAPSHOT = {
    "status": "OK",
    "ticker": {
        "ticker": "AAPL",
        "day": {"c": 120.4229, "h": 120.53, "l": 118.81, "o": 119.62, "v": 28727868},
        "lastTrade": {"p": 120.47, "s": 236, "t": 1605195918306274000},
        "min": {"c": 120.4201, "t": 1605195900000, "v": 270796},
        "prevDay": {"c": 119.49, "h": 119.63, "l": 116.44, "o": 117.19, "v": 110597265},
        "todaysChange": 0.98,
        "todaysChangePerc": 0.82,
        "updated": 1605195918306274000,
    },
}

_AGGREGATES = {
    "status": "OK",
    "ticker": "AAPL",
    "resultsCount": 2,
    "results": [
        {"t": 1704171600000, "o": 100.0, "h": 105.0, "l": 99.0, "c": 104.0, "v": 1500000},
        {"t": 1704258000000, "o": 104.0, "h": 108.5, "l": 103.5, "c": 107.25, "v": 1750000.0},
    ],
}

_RATIOS = {
    "status": "OK",
    "results": [
        {
            "ticker": "AAPL",
            "market_cap": 3050000000000,
            "enterprise_value": 3100000000000,
            "price_to_earnings": 31.2,
            "price_to_book": 48.9,
            "price_to_sales": 8.1,
            "earnings_per_share": 6.42,
            "dividend_yield": 0.0044,
            "average_volume": 54000000,
        }
    ],
}

_TICKER_SEARCH = {
    "status": "OK",
    "count": 3,
    "results": [
        {"ticker": "AAPL", "name": "Apple Inc.", "primary_exchange": "XNAS", "type": "CS"},
        {"ticker": "AAPD", "name": "Direxion Daily AAPL Bear 1X", "primary_exchange": "ARCX", "type": "ETF"},
        {"ticker": "", "name": "junk row with no ticker", "type": "CS"},
    ],
}


class _StubResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _stub_http(monkeypatch, response: _StubResponse, recorder: dict | None = None):
    """Replace httpx.AsyncClient in the massive module with a stub."""
    from app.services.data_providers import massive as massive_module

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None, headers=None):
            if recorder is not None:
                recorder["url"] = url
                recorder["params"] = params
                recorder["headers"] = headers
            return response

    monkeypatch.setattr(massive_module.httpx, "AsyncClient", _Client)


# ---------------------------------------------------------------------------
# Key gating
# ---------------------------------------------------------------------------


class TestKeyGating:
    def test_configured_reflects_app_level_settings(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "POLYGON_API_KEY", "")
        assert is_massive_configured() is False
        monkeypatch.setattr(settings, "POLYGON_API_KEY", TEST_KEY)
        assert is_massive_configured() is True

    def test_inert_without_key(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "POLYGON_API_KEY", "")
        with pytest.raises(ProviderError):
            MassiveProvider()

    def test_constructs_with_key(self):
        provider = MassiveProvider(api_key=TEST_KEY)
        assert provider.name == "massive"
        assert provider.capabilities == frozenset(ProviderCapability)

    async def test_key_travels_as_bearer_header_not_a_query_param(self, monkeypatch):
        """The key must never appear in the URL or query string.

        Query-string secrets leak into access logs, proxy logs and error
        messages; the Authorization header does not.
        """
        recorder: dict = {}
        _stub_http(monkeypatch, _StubResponse(200, _SNAPSHOT), recorder)
        provider = MassiveProvider(api_key=TEST_KEY)
        await provider.get_quote("AAPL")

        assert recorder["headers"]["Authorization"] == f"Bearer {TEST_KEY}"
        assert TEST_KEY not in recorder["url"]
        assert TEST_KEY not in str(recorder["params"])


# ---------------------------------------------------------------------------
# HTTP status policy
# ---------------------------------------------------------------------------


class TestStatusPolicy:
    async def test_delayed_status_is_success_not_an_error(self, monkeypatch):
        """``status: DELAYED`` is the *normal* response on the 15-min plan."""
        payload = {**_SNAPSHOT, "status": "DELAYED"}
        _stub_http(monkeypatch, _StubResponse(200, payload))
        provider = MassiveProvider(api_key=TEST_KEY)
        quote = await provider.get_quote("AAPL")
        assert quote is not None
        assert quote.price == Decimal("120.47")

    async def test_404_is_a_clean_not_found_not_a_provider_error(self, monkeypatch):
        """An unknown ticker must not count against provider health."""
        _stub_http(monkeypatch, _StubResponse(404, {"status": "NOT_FOUND"}))
        provider = MassiveProvider(api_key=TEST_KEY)
        assert await provider.get_quote("NOSUCH") is None
        assert await provider.get_history("NOSUCH") == []
        assert await provider.search("NOSUCH") == []

    async def test_401_raises_provider_error(self, monkeypatch):
        _stub_http(monkeypatch, _StubResponse(401, {"status": "NOT_AUTHORIZED"}))
        provider = MassiveProvider(api_key=TEST_KEY)
        with pytest.raises(ProviderError):
            await provider.get_quote("AAPL")

    async def test_429_raises_provider_error(self, monkeypatch):
        _stub_http(monkeypatch, _StubResponse(429, {"status": "ERROR"}))
        provider = MassiveProvider(api_key=TEST_KEY)
        with pytest.raises(ProviderError):
            await provider.get_history("AAPL")

    async def test_error_status_on_200_raises(self, monkeypatch):
        _stub_http(monkeypatch, _StubResponse(200, {"status": "ERROR", "error": "boom"}))
        provider = MassiveProvider(api_key=TEST_KEY)
        with pytest.raises(ProviderError):
            await provider.search("AAPL")

    async def test_unentitled_fundamentals_degrade_without_killing_the_provider(
        self, monkeypatch
    ):
        """A 403 on the financials dataset disables fundamentals only.

        The circuit breaker is shared across a provider's capabilities, so
        raising here would take history and search down with it every time the
        plan simply doesn't include financials.
        """
        _stub_http(monkeypatch, _StubResponse(403, {"status": "NOT_AUTHORIZED"}))
        provider = MassiveProvider(api_key=TEST_KEY)
        assert await provider.get_fundamentals("AAPL") is None

    async def test_403_on_an_entitled_surface_still_raises(self, monkeypatch):
        _stub_http(monkeypatch, _StubResponse(403, {"status": "NOT_AUTHORIZED"}))
        provider = MassiveProvider(api_key=TEST_KEY)
        with pytest.raises(ProviderError):
            await provider.get_history("AAPL")

    async def test_transport_failure_raises_provider_error(self, monkeypatch):
        from app.services.data_providers import massive as massive_module

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, *args, **kwargs):
                raise massive_module.httpx.ConnectError("no route to host")

        monkeypatch.setattr(massive_module.httpx, "AsyncClient", _Client)
        provider = MassiveProvider(api_key=TEST_KEY)
        with pytest.raises(ProviderError):
            await provider.get_history("AAPL")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class TestHistory:
    def test_parses_bars_oldest_first(self):
        bars = parse_aggregates(_AGGREGATES)
        assert len(bars) == 2
        assert bars[0].close == Decimal("104.0")
        assert bars[1].close == Decimal("107.25")
        assert bars[0].timestamp < bars[1].timestamp
        # Massive reports volume as a float; the schema wants an int.
        assert bars[1].volume == 1750000

    def test_drops_bars_without_a_close_rather_than_zero_filling(self):
        payload = {"results": [{"t": 1704171600000, "o": 1.0}, *_AGGREGATES["results"]]}
        bars = parse_aggregates(payload)
        assert len(bars) == 2
        assert all(bar.close > 0 for bar in bars)

    def test_missing_ohl_falls_back_to_close(self):
        payload = {"results": [{"t": 1704171600000, "c": 50.0}]}
        bars = parse_aggregates(payload)
        assert bars[0].open == bars[0].high == bars[0].low == Decimal("50.0")

    def test_empty_payload_is_empty_list(self):
        assert parse_aggregates({}) == []
        assert parse_aggregates({"results": None}) == []

    async def test_interval_and_period_map_into_the_url(self, monkeypatch):
        recorder: dict = {}
        _stub_http(monkeypatch, _StubResponse(200, _AGGREGATES), recorder)
        provider = MassiveProvider(api_key=TEST_KEY)
        await provider.get_history("aapl", period="1mo", interval="15m")
        assert "/v2/aggs/ticker/AAPL/range/15/minute/" in recorder["url"]

    async def test_unknown_interval_falls_back_to_daily(self, monkeypatch):
        recorder: dict = {}
        _stub_http(monkeypatch, _StubResponse(200, _AGGREGATES), recorder)
        provider = MassiveProvider(api_key=TEST_KEY)
        await provider.get_history("AAPL", interval="3y")
        assert "/range/1/day/" in recorder["url"]


# ---------------------------------------------------------------------------
# Quote parsing
# ---------------------------------------------------------------------------


class TestSnapshotParsing:
    def test_maps_snapshot_fields(self):
        quote = parse_snapshot("aapl", _SNAPSHOT)
        assert quote is not None
        assert quote.symbol == "AAPL"
        assert quote.price == Decimal("120.47")  # last trade wins
        assert quote.previous_close == Decimal("119.49")
        assert quote.change == Decimal("0.98")
        assert quote.change_percent == Decimal("0.82")
        assert quote.volume == 28727868
        assert quote.source == "massive"

    def test_nanosecond_timestamp_is_not_read_as_milliseconds(self):
        """``lastTrade.t`` is nanoseconds; misreading it lands in year ~50,000,000."""
        quote = parse_snapshot("AAPL", _SNAPSHOT)
        assert quote.timestamp.year == 2020
        assert quote.timestamp == datetime(2020, 11, 12, 15, 45, 18, 306000)

    def test_premarket_zero_filled_day_bar_falls_back_to_previous_session(self):
        """Massive zero-fills ``day`` before the open — never quote $0.00."""
        payload = {
            "ticker": {
                "ticker": "AAPL",
                "day": {"c": 0, "h": 0, "l": 0, "o": 0, "v": 0},
                "prevDay": {"c": 119.49, "h": 119.63, "l": 116.44, "o": 117.19, "v": 110597265},
                "updated": 1605195918306274000,
            }
        }
        quote = parse_snapshot("AAPL", payload)
        assert quote is not None
        assert quote.price == Decimal("119.49")
        assert quote.open == Decimal("117.19")
        assert quote.volume == 110597265

    def test_change_is_derived_when_massive_omits_it(self):
        payload = {
            "ticker": {
                "ticker": "AAPL",
                "day": {"c": 110.0, "o": 105.0, "h": 111.0, "l": 104.0, "v": 10},
                "prevDay": {"c": 100.0},
                "updated": 1605195918306274000,
            }
        }
        quote = parse_snapshot("AAPL", payload)
        assert quote.change == Decimal("10.0")
        assert quote.change_percent == Decimal("10")

    def test_unknown_symbol_returns_none(self):
        assert parse_snapshot("NOPE", {}) is None
        assert parse_snapshot("NOPE", {"ticker": {}}) is None


class TestSnapshotTimestampIsNeverFabricated:
    """A price of unknown age must not be presented as current.

    The parser used to fall back to ``datetime.now()`` when every timestamp
    field was missing, stamping a possibly-previous-session price with the
    fetch time. ``QuoteResponse.timestamp`` is a required non-null ``datetime``
    the UI renders verbatim as "as of", so there is no value that means
    "unknown" — and the snapshot's ``day``/``prevDay`` bars carry no time field
    to derive one from. Refusing to quote is the only answer that cannot
    mislead, and it is a clean not-found, so the chain just moves on.
    """

    _PRICED_BUT_TIMELESS = {
        "ticker": {
            "ticker": "AAPL",
            "day": {"c": 120.42, "h": 120.53, "l": 118.81, "o": 119.62, "v": 28727868},
            "prevDay": {"c": 119.49},
        }
    }

    def test_a_snapshot_with_no_usable_timestamp_is_not_quoted(self):
        assert parse_snapshot("AAPL", self._PRICED_BUT_TIMELESS) is None

    def test_it_is_a_clean_not_found_not_a_provider_failure(self):
        """A degenerate payload must not count against provider health, exactly
        like an unknown ticker — otherwise it could trip the breaker."""
        try:
            result = parse_snapshot("AAPL", self._PRICED_BUT_TIMELESS)
        except ProviderError as exc:  # pragma: no cover - guards a regression
            pytest.fail(f"a timeless snapshot raised instead of returning None: {exc}")
        assert result is None

    @pytest.mark.parametrize(
        "field,payload",
        [
            ("lastTrade.t", {"lastTrade": {"p": 120.47, "t": 1605195918306274000}}),
            ("updated", {"updated": 1605195918306274000}),
            ("min.t", {"min": {"c": 120.42, "t": 1605195900000}}),
        ],
    )
    def test_any_one_real_timestamp_field_is_enough(self, field, payload):
        """Falling back to ``None`` must not make the provider useless — any one
        of the three documented time fields still yields a quote."""
        merged = {"ticker": {**self._PRICED_BUT_TIMELESS["ticker"], **payload}}
        quote = parse_snapshot("AAPL", merged)
        assert quote is not None, f"{field} alone should have been enough"
        assert quote.timestamp.year == 2020

    def test_the_timestamp_is_data_age_not_fetch_time(self):
        """The whole point: the 2020 trade time survives, un-refreshed."""
        quote = parse_snapshot("AAPL", _SNAPSHOT)
        assert quote.timestamp == datetime(2020, 11, 12, 15, 45, 18, 306000)
        assert quote.timestamp < datetime.now(), "the trade time was refreshed"


class TestSourceStampsItsOwnStaleness:
    """A contractually delayed provider tells the truth about itself.

    ``stale`` used to be left ``False`` here on the theory that the failover
    layer owns the flag. That made the guarantee conditional on being wrapped
    in a ``FailoverQuoteProvider``: used directly, or wrapped only in
    ``ResilientProvider``, a 15-minute-delayed quote came back marked fresh.
    """

    def test_the_parser_marks_a_delayed_quote_stale(self):
        assert parse_snapshot("AAPL", _SNAPSHOT).stale is True

    async def test_stale_survives_a_direct_call_with_no_failover_layer(self, monkeypatch):
        _stub_http(monkeypatch, _StubResponse(200, _SNAPSHOT), {})
        quote = await MassiveProvider(api_key=TEST_KEY).get_quote("AAPL")
        assert quote.stale is True

    async def test_stale_survives_a_resilient_wrapper_alone(self, monkeypatch):
        """``ResilientProvider`` adds retry/breaker and no freshness logic at
        all — the flag has to come from underneath it."""
        _stub_http(monkeypatch, _StubResponse(200, _SNAPSHOT), {})
        wrapped = ResilientProvider(MassiveProvider(api_key=TEST_KEY))
        quote = await wrapped.get_quote("AAPL")
        assert quote.stale is True

    async def test_it_composes_with_the_monotonic_failover_stamp(self):
        """Proof the two layers agree instead of fighting.

        ``_stamp_stale`` is ``quote.stale or stale``, so the source's ``True``
        is preserved whichever way the failover layer would have computed it —
        including the case where the delayed provider is the chain's head
        (index 0), where the failover layer's own argument would have said
        ``False`` before the delayed-provider rule was added. No double-marking
        is possible: the flag is a bool, not a counter.
        """
        parsed = parse_snapshot("AAPL", _SNAPSHOT)
        assert parsed.stale is True

        stamped = _stamp_stale(parsed, "massive", stale=False)
        assert stamped.stale is True, "the source's own staleness was downgraded"
        assert _stamp_stale(stamped, "massive", stale=True).stale is True

    async def test_the_chain_reports_it_once_and_from_the_head(self, monkeypatch):
        """End to end: Massive alone in a chain, at index 0, still stale."""
        _stub_http(monkeypatch, _StubResponse(200, _SNAPSHOT), {})
        chain = FailoverQuoteProvider(
            [ResilientProvider(MassiveProvider(api_key=TEST_KEY))]
        )
        quote = await chain.get_quote("AAPL")
        assert quote.stale is True
        assert quote.source == "massive"

    def test_live_siblings_still_report_themselves_fresh(self):
        """Not sticky — self-stamping is scoped to the delayed provider."""
        assert _quote("yahoo", "100").stale is False


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------


class TestFundamentals:
    def test_maps_ratio_fields(self):
        fundamentals = parse_ratios(_RATIOS)
        assert fundamentals is not None
        assert fundamentals.market_cap == 3050000000000
        assert fundamentals.enterprise_value == 3100000000000
        assert fundamentals.pe_ratio == Decimal("31.2")
        assert fundamentals.price_to_book == Decimal("48.9")
        assert fundamentals.price_to_sales == Decimal("8.1")
        assert fundamentals.eps_ttm == Decimal("6.42")
        assert fundamentals.avg_volume == 54000000

    def test_dividend_yield_stays_a_fraction(self):
        """The app's canonical scale is a FRACTION and Massive already reports one.

        Unlike yfinance (which flips between fraction and percent across
        releases) this needs no rescaling — the DB column is Numeric(5, 4) and
        the frontend multiplies by 100 to display.
        """
        assert parse_ratios(_RATIOS).dividend_yield == Decimal("0.0044")

    def test_fields_this_slice_does_not_serve_are_none(self):
        fundamentals = parse_ratios(_RATIOS)
        assert fundamentals.forward_pe is None
        assert fundamentals.peg_ratio is None
        assert fundamentals.beta is None
        assert fundamentals.week_52_high is None
        assert fundamentals.week_52_low is None
        assert fundamentals.profit_margin is None

    def test_empty_results_return_none(self):
        assert parse_ratios({}) is None
        assert parse_ratios({"results": []}) is None

    def test_all_none_row_returns_none_so_the_chain_keeps_looking(self):
        """An all-empty FundamentalsResponse would short-circuit the failover
        chain and hand the UI a blank card; ``None`` lets a richer provider
        answer instead."""
        assert parse_ratios({"results": [{"ticker": "AAPL"}]}) is None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_maps_results_and_asset_types(self):
        results = parse_ticker_search(_TICKER_SEARCH)
        assert [r.symbol for r in results] == ["AAPL", "AAPD"]
        assert results[0].name == "Apple Inc."
        assert results[0].exchange == "XNAS"
        assert results[0].asset_type == "stock"
        assert results[1].asset_type == "etf"

    def test_respects_the_limit(self):
        assert len(parse_ticker_search(_TICKER_SEARCH, limit=1)) == 1

    def test_empty_payload_is_empty_list(self):
        assert parse_ticker_search({}) == []

    async def test_search_query_is_sent_as_a_stocks_scoped_lookup(self, monkeypatch):
        recorder: dict = {}
        _stub_http(monkeypatch, _StubResponse(200, _TICKER_SEARCH), recorder)
        provider = MassiveProvider(api_key=TEST_KEY)
        results = await provider.search("apple", limit=5)
        assert recorder["params"]["search"] == "apple"
        assert recorder["params"]["market"] == "stocks"
        assert len(results) == 2


# ---------------------------------------------------------------------------
# THE regression: a delayed provider must never outrank a live one for quotes
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


class _LiveProvider(MarketDataProvider):
    """A live (non-delayed) quote source that records whether it was called."""

    capabilities = frozenset(ProviderCapability)
    delayed_quotes = False

    def __init__(self, name: str = "live", price: str = "100", quote: bool = True):
        self.name = name
        self._price = price
        self._quote = quote
        self.calls = 0

    async def get_quote(self, symbol: str) -> QuoteResponse | None:
        self.calls += 1
        return _quote(self.name, self._price) if self._quote else None


class _DelayedProvider(_LiveProvider):
    """Stands in for Massive: same shape, contractually delayed."""

    delayed_quotes = True
    quote_delay_minutes = 15

    def __init__(self, name: str = "massive", price: str = "90", quote: bool = True):
        super().__init__(name=name, price=price, quote=quote)


class TestDelayedQuoteChainPosition:
    def test_massive_declares_itself_delayed(self):
        provider = MassiveProvider(api_key=TEST_KEY)
        assert provider.delayed_quotes is True
        assert provider.quote_delay_minutes == 15

    def test_live_providers_are_not_delayed_by_default(self):
        """The flag is opt-in, so adding it cannot have reordered the existing
        chain (Yahoo -> Stooq -> Alpha Vantage)."""
        from app.services.data_providers.alpha_vantage import AlphaVantageProvider
        from app.services.data_providers.stooq import StooqProvider
        from app.services.data_providers.yahoo import YahooFinanceProvider

        assert YahooFinanceProvider().delayed_quotes is False
        assert StooqProvider().delayed_quotes is False
        assert AlphaVantageProvider(api_key=TEST_KEY).delayed_quotes is False

    def test_resilient_wrapper_preserves_the_delayed_flag(self):
        """Wrapping must not launder a delayed provider into a live one — the
        chain wraps every provider in ResilientProvider, so a dropped flag here
        would defeat the ordering entirely."""
        wrapped = ResilientProvider(MassiveProvider(api_key=TEST_KEY))
        assert wrapped.delayed_quotes is True
        assert wrapped.quote_delay_minutes == 15

    async def test_live_source_is_preferred_and_delayed_is_never_consulted(self):
        """The core guarantee: a healthy live source answers, Massive is never
        even asked."""
        live = _LiveProvider(name="yahoo", price="100")
        delayed = _DelayedProvider(price="90")
        failover = FailoverQuoteProvider([live, delayed])

        quote = await failover.get_quote("AAPL")

        assert quote.source == "yahoo"
        assert quote.price == Decimal("100")
        assert quote.stale is False
        assert live.calls == 1
        assert delayed.calls == 0, "the 15-min delayed provider must not be consulted"

    async def test_ordering_survives_a_mis_ordered_chain(self):
        """The regression that matters most.

        Someone edits ``get_quote_provider()`` and puts Massive first — by
        accident, or because it is the "paid, better" provider. Without a
        structural guarantee that silently serves 15-minute-old prices as
        current. The failover layer must demote it anyway.
        """
        delayed = _DelayedProvider(price="90")
        live = _LiveProvider(name="yahoo", price="100")
        # Deliberately wrong order — delayed placed FIRST.
        failover = FailoverQuoteProvider([delayed, live])

        assert [p.name for p in failover.quote_order()] == ["yahoo", "massive"]

        quote = await failover.get_quote("AAPL")
        assert quote.source == "yahoo"
        assert delayed.calls == 0

    async def test_delayed_is_still_reachable_when_every_live_source_fails(self):
        """Demoted, not disabled — it is a real fallback, just the last one."""
        dead = _LiveProvider(name="yahoo", quote=False)
        delayed = _DelayedProvider(price="90")
        failover = FailoverQuoteProvider([dead, delayed])

        quote = await failover.get_quote("AAPL")

        assert quote.source == "massive"
        assert quote.price == Decimal("90")
        assert quote.stale is True

    async def test_a_delayed_quote_is_always_stamped_stale(self):
        """Even as the only configured source, a delayed price is never fresh."""
        delayed = _DelayedProvider(price="90")
        failover = FailoverQuoteProvider([delayed])

        quote = await failover.get_quote("AAPL")

        assert quote.source == "massive"
        assert quote.stale is True

    async def test_live_providers_keep_their_relative_order(self):
        """Demotion is a stable partition: it must not reshuffle live sources."""
        first = _LiveProvider(name="yahoo")
        second = _LiveProvider(name="stooq")
        third = _LiveProvider(name="alpha_vantage")
        delayed = _DelayedProvider()
        failover = FailoverQuoteProvider([first, delayed, second, third])

        assert [p.name for p in failover.quote_order()] == [
            "yahoo",
            "stooq",
            "alpha_vantage",
            "massive",
        ]

    async def test_history_ordering_is_untouched_by_the_delay_rule(self):
        """History is delay-insensitive: a daily bar from a delayed plan is
        exactly as good, so the caller's ordering stands for that capability."""

        class _HistoryProvider(MarketDataProvider):
            capabilities = frozenset({ProviderCapability.HISTORY})

            def __init__(self, name, delayed):
                self.name = name
                self.delayed_quotes = delayed
                self.calls = 0

            async def get_history(self, symbol, period="1y", interval="1d"):
                self.calls += 1
                return [
                    OHLCVData(
                        timestamp=datetime(2026, 8, 14),
                        open=Decimal("1"),
                        high=Decimal("1"),
                        low=Decimal("1"),
                        close=Decimal("1"),
                        volume=1,
                    )
                ]

        delayed_first = _HistoryProvider("massive", True)
        live_second = _HistoryProvider("yahoo", False)
        failover = FailoverQuoteProvider([delayed_first, live_second])

        await failover.get_history("AAPL")

        assert delayed_first.calls == 1, "history keeps the caller's ordering"
        assert live_second.calls == 0


class TestChainWiring:
    """``get_quote_provider()`` builds the chain with Massive appended last."""

    def test_absent_without_a_key(self, monkeypatch):
        from app.core.config import settings
        from app.services import data_providers

        monkeypatch.setattr(settings, "POLYGON_API_KEY", "")
        monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "")
        data_providers.reset_quote_provider()
        try:
            chain = data_providers.get_quote_provider()
            assert "massive" not in [p.name for p in chain.providers]
        finally:
            data_providers.reset_quote_provider()

    def test_appended_last_when_keyed(self, monkeypatch):
        from app.core.config import settings
        from app.services import data_providers

        monkeypatch.setattr(settings, "POLYGON_API_KEY", TEST_KEY)
        monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "")
        data_providers.reset_quote_provider()
        try:
            chain = data_providers.get_quote_provider()
            names = [p.name for p in chain.providers]
            assert names[-1] == "massive"
            assert names[0] == "yahoo"
            # And the enforced quote order agrees with the hand-built order.
            assert [p.name for p in chain.quote_order()][-1] == "massive"
        finally:
            data_providers.reset_quote_provider()

    def test_massive_supports_every_capability_in_the_chain(self, monkeypatch):
        from app.core.config import settings
        from app.services import data_providers

        monkeypatch.setattr(settings, "POLYGON_API_KEY", TEST_KEY)
        data_providers.reset_quote_provider()
        try:
            chain = data_providers.get_quote_provider()
            massive = next(p for p in chain.providers if p.name == "massive")
            for capability in ProviderCapability:
                assert massive.supports(capability)
        finally:
            data_providers.reset_quote_provider()
