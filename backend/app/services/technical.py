"""Technical analysis service - calculate technical indicators from price data."""

from decimal import Decimal
from typing import List, Optional

from app.schemas.equity import OHLCVData


def to_float(value: Decimal | float | str) -> float:
    """Convert value to float for calculations."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        return float(value)
    return value


class TechnicalIndicators:
    """Calculate technical indicators from OHLCV data."""

    @staticmethod
    def sma(closes: List[float], period: int) -> List[Optional[float]]:
        """Calculate Simple Moving Average."""
        result = []
        for i in range(len(closes)):
            if i < period - 1:
                result.append(None)
            else:
                window = closes[i - period + 1 : i + 1]
                result.append(sum(window) / period)
        return result

    @staticmethod
    def ema(closes: List[float], period: int) -> List[Optional[float]]:
        """Calculate Exponential Moving Average."""
        result = []
        multiplier = 2 / (period + 1)

        for i in range(len(closes)):
            if i < period - 1:
                result.append(None)
            elif i == period - 1:
                # First EMA is SMA
                sma = sum(closes[: period]) / period
                result.append(sma)
            else:
                prev_ema = result[-1]
                if prev_ema is not None:
                    ema = (closes[i] - prev_ema) * multiplier + prev_ema
                    result.append(ema)
                else:
                    result.append(None)
        return result

    @staticmethod
    def rsi(closes: List[float], period: int = 14) -> List[Optional[float]]:
        """Calculate Relative Strength Index."""
        if len(closes) < period + 1:
            return [None] * len(closes)

        result = [None] * period
        gains = []
        losses = []

        # Calculate initial gains and losses
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        # Calculate first RSI
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - (100 / (1 + rs)))

        # Calculate subsequent RSIs using smoothed averages
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

            if avg_loss == 0:
                result.append(100.0)
            else:
                rs = avg_gain / avg_loss
                result.append(100 - (100 / (1 + rs)))

        return result

    @staticmethod
    def macd(
        closes: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> dict:
        """Calculate MACD (Moving Average Convergence Divergence)."""
        ema_fast = TechnicalIndicators.ema(closes, fast_period)
        ema_slow = TechnicalIndicators.ema(closes, slow_period)

        macd_line = []
        for i in range(len(closes)):
            if ema_fast[i] is not None and ema_slow[i] is not None:
                macd_line.append(ema_fast[i] - ema_slow[i])
            else:
                macd_line.append(None)

        # Calculate signal line (EMA of MACD)
        macd_values = [v for v in macd_line if v is not None]
        signal_ema = TechnicalIndicators.ema(macd_values, signal_period)

        # Align signal line with MACD
        signal_line = [None] * (len(macd_line) - len(signal_ema)) + signal_ema

        # Calculate histogram
        histogram = []
        for i in range(len(macd_line)):
            if macd_line[i] is not None and signal_line[i] is not None:
                histogram.append(macd_line[i] - signal_line[i])
            else:
                histogram.append(None)

        return {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": histogram,
        }

    @staticmethod
    def bollinger_bands(
        closes: List[float], period: int = 20, std_dev: float = 2.0
    ) -> dict:
        """Calculate Bollinger Bands."""
        import math

        sma = TechnicalIndicators.sma(closes, period)

        upper = []
        lower = []
        middle = sma

        for i in range(len(closes)):
            if i < period - 1:
                upper.append(None)
                lower.append(None)
            else:
                window = closes[i - period + 1 : i + 1]
                mean = sma[i]
                if mean is not None:
                    variance = sum((x - mean) ** 2 for x in window) / period
                    std = math.sqrt(variance)
                    upper.append(mean + std_dev * std)
                    lower.append(mean - std_dev * std)
                else:
                    upper.append(None)
                    lower.append(None)

        return {
            "upper": upper,
            "middle": middle,
            "lower": lower,
        }


class TechnicalAnalysisService:
    """Service for technical analysis calculations."""

    def __init__(self):
        self.indicators = TechnicalIndicators()

    def calculate_all(
        self, history: List[OHLCVData]
    ) -> dict:
        """Calculate all technical indicators for the given history."""
        if not history:
            return {}

        closes = [to_float(h.close) for h in history]
        timestamps = [h.timestamp for h in history]

        # Calculate indicators
        sma_20 = self.indicators.sma(closes, 20)
        sma_50 = self.indicators.sma(closes, 50)
        sma_200 = self.indicators.sma(closes, 200)
        ema_12 = self.indicators.ema(closes, 12)
        ema_26 = self.indicators.ema(closes, 26)
        rsi = self.indicators.rsi(closes, 14)
        macd_data = self.indicators.macd(closes)
        bb_data = self.indicators.bollinger_bands(closes)

        return {
            "timestamps": [t.isoformat() if hasattr(t, 'isoformat') else str(t) for t in timestamps],
            "closes": closes,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "ema_12": ema_12,
            "ema_26": ema_26,
            "rsi": rsi,
            "macd": macd_data["macd"],
            "macd_signal": macd_data["signal"],
            "macd_histogram": macd_data["histogram"],
            "bb_upper": bb_data["upper"],
            "bb_middle": bb_data["middle"],
            "bb_lower": bb_data["lower"],
        }

    def get_summary(self, history: List[OHLCVData]) -> dict:
        """Get a summary of current technical indicator values."""
        if not history or len(history) < 2:
            return {}

        closes = [to_float(h.close) for h in history]
        current_price = closes[-1]

        sma_20 = self.indicators.sma(closes, 20)
        sma_50 = self.indicators.sma(closes, 50)
        sma_200 = self.indicators.sma(closes, 200)
        rsi = self.indicators.rsi(closes, 14)
        macd_data = self.indicators.macd(closes)

        return {
            "price": current_price,
            "sma_20": sma_20[-1] if sma_20[-1] else None,
            "sma_50": sma_50[-1] if sma_50[-1] else None,
            "sma_200": sma_200[-1] if sma_200[-1] else None,
            "rsi": rsi[-1] if rsi[-1] else None,
            "macd": macd_data["macd"][-1] if macd_data["macd"][-1] else None,
            "macd_signal": macd_data["signal"][-1] if macd_data["signal"][-1] else None,
            "above_sma_20": current_price > sma_20[-1] if sma_20[-1] else None,
            "above_sma_50": current_price > sma_50[-1] if sma_50[-1] else None,
            "above_sma_200": current_price > sma_200[-1] if sma_200[-1] else None,
            "rsi_signal": (
                "overbought" if rsi[-1] and rsi[-1] > 70 else
                "oversold" if rsi[-1] and rsi[-1] < 30 else
                "neutral"
            ) if rsi[-1] else None,
        }
