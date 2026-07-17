"""Regression tests for dividendYield ingestion-scale normalization (Queue S S2).

yfinance reports ``dividendYield`` as a fraction (``0.025`` for 2.5%) in older
releases and as a percent (``2.5`` for 2.5%) in the 1.x line; the pinned
``==1.1.0`` always returns a percent. ``_normalize_dividend_yield`` maps the
value to the canonical FRACTION scale at the provider boundary, so the stored
value and every downstream ×100 display (FundamentalsCard, PeerComparison, the
AI context) stay correct.

Two paths:
- PRIMARY (defense-in-depth): when dividendRate + price are present, cross-check
  against the rate/price-implied yield. The fraction/percent readings are always
  100x apart, so this is robust to EITHER input shape and resolves the ambiguous
  sub-1% case.
- FALLBACK (no ground truth): scale down unconditionally, matching the pinned
  yfinance's percent shape. A magnitude heuristic would leave a genuine sub-1%
  percent yield (e.g. 0.32 -> 0.32) mis-scaled 100x.
"""

import logging
from decimal import Decimal

import pytest

from app.services.data_providers.yahoo import _normalize_dividend_yield


class TestCrossCheckPath:
    """PRIMARY path: rate/price present -> robust to BOTH input shapes."""

    @pytest.mark.parametrize(
        "percent_input,fraction_input,rate,price,expected",
        [
            # both shapes of the SAME real yield collapse to one canonical fraction
            (Decimal("2.5"), Decimal("0.025"), Decimal("2.12"), Decimal("81.56"), Decimal("0.025")),      # KO
            (Decimal("5.05"), Decimal("0.0505"), Decimal("1.11"), Decimal("21.81"), Decimal("0.0505")),   # T
            (Decimal("0.32"), Decimal("0.0032"), Decimal("1.08"), Decimal("333.74"), Decimal("0.0032")),  # AAPL (sub-1%)
        ],
    )
    def test_both_shapes_collapse_to_same_fraction(
        self, percent_input, fraction_input, rate, price, expected
    ):
        from_percent = _normalize_dividend_yield(percent_input, rate, price)
        from_fraction = _normalize_dividend_yield(fraction_input, rate, price)
        assert from_percent == expected
        assert from_fraction == expected
        assert from_percent == from_fraction


class TestFallbackPath:
    """FALLBACK path: no rate/price -> assume percent (the pinned shape), ÷100."""

    @pytest.mark.parametrize(
        "percent_input,expected",
        [
            (Decimal("2.5"), Decimal("0.025")),    # ticket example
            (Decimal("5.05"), Decimal("0.0505")),  # T
            (Decimal("12.0"), Decimal("0.12")),    # would overflow Numeric(5,4) if left raw
            # The exact case that shipped unguarded: a genuine sub-1% percent
            # yield whose value is itself < 1. The old `raw>1 ? ÷100 : keep`
            # fallback wrongly KEPT these (rendering 32% / 50%).
            (Decimal("0.32"), Decimal("0.0032")),  # AAPL 0.32%
            (Decimal("0.5"), Decimal("0.005")),    # 0.5%
        ],
    )
    def test_no_ground_truth_scales_down_unconditionally(self, percent_input, expected):
        assert _normalize_dividend_yield(percent_input) == expected

    def test_sub_one_percent_regression_vs_old_keep_fallback(self):
        """Directly pins the fix: under the removed `raw>1 ? ÷100 : keep`
        fallback these returned 0.32 (=32%) / 0.5 (=50%); the tightened fallback
        returns the correct 0.0032 (=0.32%) / 0.005 (=0.5%).
        """
        assert _normalize_dividend_yield(Decimal("0.32")) == Decimal("0.0032")
        assert _normalize_dividend_yield(Decimal("0.5")) == Decimal("0.005")

    def test_fallback_emits_warning(self, caplog):
        """The no-cross-check branch warns so a future pin-shape change is visible."""
        with caplog.at_level(logging.WARNING, logger="app.services.data_providers.yahoo"):
            _normalize_dividend_yield(Decimal("2.5"))
        assert any(
            "without a rate/price cross-check" in r.getMessage() for r in caplog.records
        )

    def test_rate_price_ignored_when_price_missing_or_zero(self):
        """Unusable ground truth falls through to the percent-scale fallback."""
        assert _normalize_dividend_yield(Decimal("2.5"), Decimal("1.08"), None) == Decimal("0.025")
        assert _normalize_dividend_yield(Decimal("2.5"), Decimal("1.08"), Decimal("0")) == Decimal("0.025")


class TestCanonicalScaleAndEdges:
    def test_canonical_scale_renders_correctly(self):
        # downstream multiplies by 100; a 2.5% yield must render as 2.50%.
        assert _normalize_dividend_yield(Decimal("2.5")) * 100 == Decimal("2.5")
        # a fraction-shaped input resolves correctly via the cross-check path.
        assert (
            _normalize_dividend_yield(Decimal("0.025"), Decimal("2.12"), Decimal("81.56")) * 100
            == Decimal("2.5")
        )

    def test_float_inputs_supported(self):
        """yfinance hands over Python floats, not Decimals."""
        assert _normalize_dividend_yield(2.5) == Decimal("0.025")
        assert _normalize_dividend_yield(0.32) == Decimal("0.0032")

    def test_none_passes_through(self):
        assert _normalize_dividend_yield(None) is None

    def test_nan_returns_none(self):
        assert _normalize_dividend_yield(float("nan")) is None

    def test_zero_stays_zero(self):
        assert _normalize_dividend_yield(Decimal("0")) == Decimal("0")
        assert _normalize_dividend_yield(0) == Decimal("0")
