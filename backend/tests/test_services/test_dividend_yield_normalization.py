"""Regression tests for dividendYield ingestion-scale normalization (Queue S S2).

yfinance reports ``dividendYield`` as a fraction (``0.025`` for 2.5%) in older
releases and as a percent (``2.5`` for 2.5%) in the 1.x line. With the dependency
previously pinned to a floating ``>=0.2.36`` floor, the same field could be
ingested — and therefore stored and rendered — 100x off.

``_normalize_dividend_yield`` collapses both shapes to the canonical FRACTION
scale at the provider boundary, so the stored value and every downstream ×100
display (FundamentalsCard, PeerComparison, the AI context) stay correct
regardless of which yfinance version the environment resolves.
"""

from decimal import Decimal

import pytest

from app.services.data_providers.yahoo import _normalize_dividend_yield


class TestNormalizeDividendYield:
    @pytest.mark.parametrize(
        "percent_input,fraction_input,expected",
        [
            # (percent-shaped input, fraction-shaped input, canonical fraction)
            (Decimal("2.5"), Decimal("0.025"), Decimal("0.025")),      # ticket example
            (Decimal("2.5"), Decimal("0.025"), Decimal("0.025")),      # KO (empirical, yfinance 1.1.0)
            (Decimal("5.05"), Decimal("0.0505"), Decimal("0.0505")),   # T (empirical, yfinance 1.1.0)
            (Decimal("1.5"), Decimal("0.015"), Decimal("0.015")),
            (Decimal("12.0"), Decimal("0.12"), Decimal("0.12")),       # percent form would overflow Numeric(5,4)
        ],
    )
    def test_both_shapes_collapse_to_same_fraction(
        self, percent_input: Decimal, fraction_input: Decimal, expected: Decimal
    ):
        """Both a percent-shaped and a fraction-shaped input normalize to the
        SAME canonical fraction. Yields at or above ~1% are unambiguous by
        magnitude (the percent form is > 1), so no rate/price context is needed.
        """
        assert _normalize_dividend_yield(percent_input) == expected
        assert _normalize_dividend_yield(fraction_input) == expected
        assert _normalize_dividend_yield(percent_input) == _normalize_dividend_yield(
            fraction_input
        )

    def test_sub_one_percent_yield_uses_rate_price_ground_truth(self):
        """The genuinely ambiguous case: a sub-1% yield's percent form is itself
        < 1, so magnitude alone cannot tell it from a fraction. AAPL pays ~$1.08
        on a ~$333.74 price (~0.32%); rate/price disambiguates both shapes to the
        same canonical fraction.
        """
        rate, price = Decimal("1.08"), Decimal("333.74")
        from_percent = _normalize_dividend_yield(Decimal("0.32"), rate, price)
        from_fraction = _normalize_dividend_yield(Decimal("0.0032"), rate, price)
        assert from_percent == Decimal("0.0032")
        assert from_fraction == Decimal("0.0032")
        assert from_percent == from_fraction

    def test_percent_form_is_not_left_at_100x(self):
        """Regression: the pre-fix code stored ``info['dividendYield']`` verbatim,
        so a percent-returning yfinance stored 2.5 and the ×100 UI rendered 250%.
        """
        normalized = _normalize_dividend_yield(Decimal("2.5"))
        assert normalized == Decimal("0.025")
        assert normalized != Decimal("2.5")

    def test_canonical_scale_renders_correctly(self):
        """Downstream (frontend + AI) multiply by 100; a 2.5% yield must render
        as 2.50% from either input shape.
        """
        assert _normalize_dividend_yield(Decimal("2.5")) * 100 == Decimal("2.5")
        assert _normalize_dividend_yield(Decimal("0.025")) * 100 == Decimal("2.5")

    def test_float_inputs_supported(self):
        """yfinance hands over Python floats, not Decimals."""
        assert _normalize_dividend_yield(2.5) == Decimal("0.025")
        assert _normalize_dividend_yield(0.025) == Decimal("0.025")

    def test_none_passes_through(self):
        assert _normalize_dividend_yield(None) is None

    def test_nan_returns_none(self):
        assert _normalize_dividend_yield(float("nan")) is None

    def test_zero_stays_zero(self):
        assert _normalize_dividend_yield(Decimal("0")) == Decimal("0")
        assert _normalize_dividend_yield(0) == Decimal("0")

    def test_rate_price_ignored_when_price_missing_or_zero(self):
        """Falls back to the magnitude heuristic when ground truth is unusable."""
        assert _normalize_dividend_yield(Decimal("2.5"), Decimal("1.08"), None) == Decimal("0.025")
        assert _normalize_dividend_yield(Decimal("2.5"), Decimal("1.08"), Decimal("0")) == Decimal("0.025")
