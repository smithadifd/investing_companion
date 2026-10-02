"""Offline checks for indicators calculated from fixed price histories."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import isnan, sqrt

import pytest

from app.schemas.equity import OHLCVData
from app.services.technical import TechnicalAnalysisService, TechnicalIndicators, to_float


def _history(closes: list[Decimal | str | float], volume: int = 100) -> list[OHLCVData]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        OHLCVData(
            timestamp=start + timedelta(days=index),
            open=Decimal(str(close)),
            high=Decimal(str(close)),
            low=Decimal(str(close)),
            close=close,
            volume=volume,
        )
        for index, close in enumerate(closes)
    ]


class TestToFloat:
    def test_decimal(self):
        assert to_float(Decimal("12.25")) == 12.25

    def test_string(self):
        assert to_float("12.25") == 12.25

    def test_float(self):
        assert to_float(12.25) == 12.25


class TestTechnicalIndicators:
    def test_sma_uses_trailing_window(self):
        # (1 + 2 + 3) / 3 = 2; (2 + 3 + 6) / 3 = 11/3.
        assert TechnicalIndicators.sma([1, 2, 3, 6], 3) == [None, None, 2, 11 / 3]

    def test_sma_short_series(self):
        assert TechnicalIndicators.sma([1, 2], 3) == [None, None]

    def test_sma_nan_in_window(self):
        values = TechnicalIndicators.sma([1, float("nan"), 3, 4], 2)
        assert values[0] is None
        assert values[1] is not None and isnan(values[1])
        assert values[2] is not None and isnan(values[2])
        assert values[3] == 3.5

    def test_ema_seeds_with_sma_then_smooths(self):
        # Seed = (1 + 3 + 5) / 3 = 3; multiplier = 2/(3+1) = 1/2.
        assert TechnicalIndicators.ema([1, 3, 5, 9, 9], 3) == [
            None, None, 3, 6, 7.5,
        ]

    def test_ema_short_series(self):
        assert TechnicalIndicators.ema([1, 3], 3) == [None, None]

    def test_rsi_initial_and_smoothed_values(self):
        # First averages: gain 4/3, loss 1/3 -> RSI 80.
        # Next: gain 8/9, loss 5/9 -> 100*8/13.
        # Last: gain 34/27, loss 10/27 -> 100*34/44.
        result = TechnicalIndicators.rsi([10, 12, 11, 13, 12, 14], 3)
        assert result[:3] == [None] * 3
        assert result[3:] == pytest.approx([80, 800 / 13, 3400 / 44])

    def test_rsi_requires_one_more_close_than_period(self):
        assert TechnicalIndicators.rsi([10, 12, 11], 3) == [None] * 3

    def test_rsi_without_losses(self):
        assert TechnicalIndicators.rsi([1, 2, 3, 4], 2) == [None, None, 100, 100]

    def test_macd_line_signal_and_histogram(self):
        # Fast EMA(2): 1.5, 2.5, ...; slow EMA(3): 2, 3, ...
        # Their difference is 0.5; the two-point signal seeds at 0.5.
        assert TechnicalIndicators.macd(
            [1, 2, 3, 4, 5, 6], fast_period=2, slow_period=3, signal_period=2
        ) == {
            "macd": [None, None, 0.5, 0.5, 0.5, 0.5],
            "signal": [None, None, None, 0.5, 0.5, 0.5],
            "histogram": [None, None, None, 0, 0, 0],
        }

    def test_macd_histogram_tracks_changing_line(self):
        # Fast EMA(2) ends at 29/6; slow EMA(3) ends at 4.
        # MACD moves from 1/2 to 5/6, so signal = 2/3 and histogram = 1/6.
        result = TechnicalIndicators.macd(
            [1, 2, 3, 6], fast_period=2, slow_period=3, signal_period=2
        )
        assert result["macd"] == pytest.approx([None, None, 1 / 2, 5 / 6])
        assert result["signal"] == pytest.approx([None, None, None, 2 / 3])
        assert result["histogram"] == pytest.approx([None, None, None, 1 / 6])

    def test_macd_short_series(self):
        assert TechnicalIndicators.macd([1, 2], 2, 3, 2) == {
            "macd": [None, None],
            "signal": [None, None],
            "histogram": [None, None],
        }

    def test_bollinger_bands_use_population_deviation(self):
        # Each two-point window has mean 2 or 4 and population deviation 1.
        assert TechnicalIndicators.bollinger_bands([1, 3, 5], 2, 2) == {
            "upper": [None, 4, 6],
            "middle": [None, 2, 4],
            "lower": [None, 0, 2],
        }

    def test_bollinger_bands_short_series(self):
        assert TechnicalIndicators.bollinger_bands([1, 3], 3) == {
            "upper": [None, None],
            "middle": [None, None],
            "lower": [None, None],
        }


class TestTechnicalAnalysisService:
    def test_calculate_all_empty_history(self):
        assert TechnicalAnalysisService().calculate_all([]) == {}

    def test_calculate_all_converts_closes_and_ignores_zero_volume(self):
        result = TechnicalAnalysisService().calculate_all(
            _history([Decimal("10"), "11", 12.0], volume=0)
        )
        assert result["timestamps"] == [
            "2024-01-01T00:00:00+00:00",
            "2024-01-02T00:00:00+00:00",
            "2024-01-03T00:00:00+00:00",
        ]
        assert result["closes"] == [10.0, 11.0, 12.0]
        for key in (
            "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "rsi",
            "macd", "macd_signal", "macd_histogram", "bb_upper",
            "bb_middle", "bb_lower",
        ):
            assert result[key] == [None] * 3, key

    def test_calculate_all_mature_history(self):
        # 200 closes at 10 followed by one at 20: trailing SMA means are
        # 10 + 10/window; EMA12's final weight is 2/13.
        result = TechnicalAnalysisService().calculate_all(_history([10] * 200 + [20]))
        assert len(result["closes"]) == 201
        assert result["sma_20"][-1] == 10.5
        assert result["sma_50"][-1] == 10.2
        assert result["sma_200"][-1] == 10.05
        assert result["ema_12"][-1] == pytest.approx(10 + 20 / 13)
        assert result["ema_26"][-1] == pytest.approx(10 + 20 / 27)
        assert result["rsi"][-1] == 100
        assert result["macd"][-1] == pytest.approx(20 / 13 - 20 / 27)
        # In the last 20 closes, nineteen deviate by -0.5 and one by +9.5.
        assert result["bb_middle"][-1] == 10.5
        assert result["bb_upper"][-1] == pytest.approx(10.5 + 2 * sqrt(4.75))
        assert result["bb_lower"][-1] == pytest.approx(10.5 - 2 * sqrt(4.75))

    def test_get_summary_requires_two_observations(self):
        service = TechnicalAnalysisService()
        assert service.get_summary([]) == {}
        assert service.get_summary(_history([10])) == {}

    def test_get_summary_current_values_and_signal(self):
        result = TechnicalAnalysisService().get_summary(_history([10] * 200 + [20]))
        assert result == {
            "price": 20.0,
            "sma_20": 10.5,
            "sma_50": 10.2,
            "sma_200": 10.05,
            "rsi": 100.0,
            "macd": pytest.approx(20 / 13 - 20 / 27),
            "macd_signal": pytest.approx((20 / 13 - 20 / 27) * 2 / 10),
            "above_sma_20": True,
            "above_sma_50": True,
            "above_sma_200": True,
            "rsi_signal": "overbought",
        }
