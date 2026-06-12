"""Tests for extended-hours quote parsing in the Yahoo provider (Phase F)."""

from app.services.data_providers.yahoo import _parse_extended_quote


def _info(market_state: str, **extra) -> dict:
    base = {
        "marketState": market_state,
        "regularMarketPrice": 100.0,
        "regularMarketChangePercent": -1.5,
    }
    base.update(extra)
    return base


class TestParseExtendedQuote:
    def test_pre_session_uses_premarket_fields(self):
        quote = _parse_extended_quote(
            _info("PRE", preMarketPrice=104.0, preMarketChangePercent=4.0)
        )
        assert quote == {"price": 104.0, "change_percent": 4.0, "session": "pre"}

    def test_pre_percent_computed_when_missing(self):
        # During pre-market, regularMarketPrice IS the prior regular close
        quote = _parse_extended_quote(_info("PRE", preMarketPrice=102.0))
        assert quote["session"] == "pre"
        assert quote["price"] == 102.0
        assert quote["change_percent"] == 2.0

    def test_pre_session_without_premarket_data_degrades_to_closed(self):
        """An illiquid ticker with no pre-market trades must not present
        yesterday's regular-session move as a pre-market move."""
        quote = _parse_extended_quote(_info("PRE"))
        assert quote["session"] == "closed"
        assert quote["price"] == 100.0
        assert quote["change_percent"] == -1.5

    def test_post_session_uses_postmarket_fields(self):
        quote = _parse_extended_quote(
            _info("POST", postMarketPrice=93.0, postMarketChangePercent=-7.0)
        )
        assert quote == {"price": 93.0, "change_percent": -7.0, "session": "post"}

    def test_post_percent_computed_when_missing(self):
        quote = _parse_extended_quote(_info("POST", postMarketPrice=97.0))
        assert quote["session"] == "post"
        assert quote["change_percent"] == -3.0

    def test_post_session_without_postmarket_data_degrades_to_closed(self):
        quote = _parse_extended_quote(_info("POST"))
        assert quote["session"] == "closed"

    def test_regular_session(self):
        quote = _parse_extended_quote(_info("REGULAR"))
        assert quote == {"price": 100.0, "change_percent": -1.5, "session": "regular"}

    def test_closed_and_overnight_states_fall_back_to_close(self):
        for state in ("CLOSED", "PREPRE", "POSTPOST", ""):
            quote = _parse_extended_quote(_info(state))
            assert quote["session"] == "closed", state
            assert quote["price"] == 100.0
            assert quote["change_percent"] == -1.5

    def test_no_regular_price_returns_none(self):
        assert _parse_extended_quote({"marketState": "PRE"}) is None

    def test_missing_regular_change_percent_is_zero(self):
        quote = _parse_extended_quote(
            {"marketState": "CLOSED", "regularMarketPrice": 50.0}
        )
        assert quote["change_percent"] == 0.0
