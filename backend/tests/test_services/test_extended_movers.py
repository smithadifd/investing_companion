"""Tests for the shared extended-hours movers builder (Phase F)."""

from unittest.mock import AsyncMock

from app.services.extended_movers import collect_extended_movers, dedupe_movers


def _provider(quotes: dict) -> AsyncMock:
    """Build a provider mock whose get_extended_quote returns from a dict."""
    provider = AsyncMock()
    provider.get_extended_quote = AsyncMock(side_effect=lambda sym: quotes.get(sym))
    return provider


class TestCollectExtendedMovers:
    async def test_pre_session_uses_premarket_changes(self):
        provider = _provider({
            "EQT": {"price": 54.0, "change_percent": 3.2, "session": "pre"},
            "CCJ": {"price": 95.0, "change_percent": -0.4, "session": "pre"},
        })

        movers, label = await collect_extended_movers(
            ["EQT", "CCJ"], provider, target_session="pre"
        )

        assert label == "pre"
        assert movers == [{"symbol": "EQT", "change_percent": 3.2}]

    async def test_stale_at_close_quotes_excluded_from_live_session(self):
        """A symbol with no pre-market data (session 'closed') must not leak
        yesterday's move into a list labeled pre-market."""
        provider = _provider({
            "EQT": {"price": 54.0, "change_percent": 3.2, "session": "pre"},
            "SRUUF": {"price": 20.0, "change_percent": 5.0, "session": "closed"},
        })

        movers, label = await collect_extended_movers(
            ["EQT", "SRUUF"], provider, target_session="pre"
        )

        assert label == "pre"
        assert [m["symbol"] for m in movers] == ["EQT"]

    async def test_regular_session_quotes_ride_along(self):
        """24h instruments (futures/forex) report 'regular' with a live change
        vs prior close - they belong next to genuine pre-market quotes."""
        provider = _provider({
            "EQT": {"price": 54.0, "change_percent": 2.1, "session": "pre"},
            "GC=F": {"price": 2700.0, "change_percent": -2.5, "session": "regular"},
        })

        movers, label = await collect_extended_movers(
            ["EQT", "GC=F"], provider, target_session="pre"
        )

        assert label == "pre"
        assert [m["symbol"] for m in movers] == ["GC=F", "EQT"]  # sorted by |change|

    async def test_no_live_data_falls_back_to_closed_label(self):
        provider = _provider({
            "EQT": {"price": 52.0, "change_percent": -2.8, "session": "closed"},
            "CCJ": {"price": 95.0, "change_percent": 1.0, "session": "closed"},
        })

        movers, label = await collect_extended_movers(
            ["EQT", "CCJ"], provider, target_session="pre"
        )

        assert label == "closed"
        assert movers == [{"symbol": "EQT", "change_percent": -2.8}]

    async def test_symbols_deduped_before_fetching(self):
        provider = _provider({
            "UUUU": {"price": 10.0, "change_percent": 4.0, "session": "pre"},
        })

        movers, _ = await collect_extended_movers(
            ["UUUU", "UUUU", "UUUU", "UUUU"], provider, target_session="pre"
        )

        assert movers == [{"symbol": "UUUU", "change_percent": 4.0}]
        assert provider.get_extended_quote.await_count == 1

    async def test_one_failing_symbol_never_breaks_the_batch(self):
        async def _get(symbol: str):
            if symbol == "BAD":
                raise RuntimeError("boom")
            return {"price": 50.0, "change_percent": 2.5, "session": "pre"}

        provider = AsyncMock()
        provider.get_extended_quote = AsyncMock(side_effect=_get)

        movers, label = await collect_extended_movers(
            ["BAD", "EQT"], provider, target_session="pre"
        )

        assert label == "pre"
        assert [m["symbol"] for m in movers] == ["EQT"]

    async def test_none_quotes_skipped(self):
        provider = _provider({
            "EQT": {"price": 54.0, "change_percent": 2.1, "session": "pre"},
        })

        movers, label = await collect_extended_movers(
            ["UNKNOWN", "EQT"], provider, target_session="pre"
        )

        assert [m["symbol"] for m in movers] == ["EQT"]

    async def test_regular_rides_along_in_post_session_too(self):
        provider = _provider({
            "EQT": {"price": 49.0, "change_percent": -6.0, "session": "post"},
            "GC=F": {"price": 2700.0, "change_percent": 2.5, "session": "regular"},
        })

        movers, label = await collect_extended_movers(
            ["EQT", "GC=F"], provider, target_session="post"
        )

        assert label == "post"
        assert [m["symbol"] for m in movers] == ["EQT", "GC=F"]

    async def test_post_session_target(self):
        provider = _provider({
            "EQT": {"price": 49.0, "change_percent": -6.0, "session": "post"},
            "CCJ": {"price": 95.0, "change_percent": 0.5, "session": "post"},
        })

        movers, label = await collect_extended_movers(
            ["EQT", "CCJ"], provider, target_session="post"
        )

        assert label == "post"
        assert movers == [{"symbol": "EQT", "change_percent": -6.0}]


class TestDedupeMovers:
    def test_ticker_in_n_watchlists_prints_once(self):
        movers = [
            {"symbol": "UUUU", "change_percent": 4.2},
            {"symbol": "EQT", "change_percent": -3.5},
            {"symbol": "UUUU", "change_percent": 4.2},
            {"symbol": "UUUU", "change_percent": 4.2},
        ]

        assert dedupe_movers(movers) == [
            {"symbol": "UUUU", "change_percent": 4.2},
            {"symbol": "EQT", "change_percent": -3.5},
        ]

    def test_empty(self):
        assert dedupe_movers([]) == []
