"""Market overview service - provides indices, sectors, movers, and currencies/commodities."""

import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Tuple

from app.schemas.market import (
    CurrencyCommodity,
    IndexQuote,
    MarketMover,
    MarketOverviewResponse,
    SectorPerformance,
)
from app.services.data_providers.yahoo import YahooFinanceProvider

logger = logging.getLogger(__name__)


# Major market indices
MARKET_INDICES = [
    ("^GSPC", "S&P 500"),
    ("^DJI", "Dow Jones"),
    ("^IXIC", "Nasdaq"),
    ("^RUT", "Russell 2000"),
    ("^VIX", "VIX"),
]

# Sector ETFs (SPDR Select Sector ETFs)
SECTOR_ETFS = [
    ("XLK", "Technology"),
    ("XLF", "Financials"),
    ("XLV", "Healthcare"),
    ("XLE", "Energy"),
    ("XLY", "Consumer Discretionary"),
    ("XLP", "Consumer Staples"),
    ("XLI", "Industrials"),
    ("XLB", "Materials"),
    ("XLU", "Utilities"),
    ("XLRE", "Real Estate"),
    ("XLC", "Communication Services"),
]

# Currencies and commodities
CURRENCIES_COMMODITIES = [
    ("DX-Y.NYB", "US Dollar Index", "currency"),
    ("EURUSD=X", "EUR/USD", "currency"),
    ("GC=F", "Gold", "commodity"),
    ("SI=F", "Silver", "commodity"),
    ("CL=F", "Crude Oil", "commodity"),
    ("NG=F", "Natural Gas", "commodity"),
    ("BTC-USD", "Bitcoin", "crypto"),
    ("ETH-USD", "Ethereum", "crypto"),
]

# Popular stocks for gainers/losers (large caps with high volume)
POPULAR_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "UNH", "JNJ", "JPM", "V", "PG", "MA", "HD", "CVX", "MRK", "ABBV",
    "PFE", "KO", "PEP", "COST", "AVGO", "TMO", "MCD", "WMT", "CSCO",
    "ACN", "ABT", "DHR", "NKE", "ORCL", "VZ", "ADBE", "CRM", "CMCSA",
    "INTC", "AMD", "NFLX", "PYPL", "T", "PM", "UNP", "NEE", "RTX",
    "HON", "LOW", "UPS", "BA", "CAT", "GS", "BLK", "SPGI", "AXP",
]


class MarketService:
    """Service for market overview data."""

    def __init__(self) -> None:
        self.yahoo = YahooFinanceProvider()

    async def _fetch_quote_data(self, symbol: str) -> Optional[dict]:
        """Fetch quote data for a symbol, returning raw dict."""
        try:
            quote = await self.yahoo.get_quote(symbol)
            if quote:
                return {
                    "symbol": symbol,
                    "price": quote.price,
                    "change": quote.change,
                    "change_percent": quote.change_percent,
                    "volume": quote.volume,
                    "timestamp": quote.timestamp,
                }
        except Exception as e:
            logger.warning(f"Failed to fetch quote for {symbol}: {e}")
        return None

    async def get_indices(self) -> List[IndexQuote]:
        """Fetch major market indices."""
        tasks = [self._fetch_quote_data(symbol) for symbol, _ in MARKET_INDICES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        indices = []
        for (symbol, name), result in zip(MARKET_INDICES, results):
            if isinstance(result, dict) and result:
                indices.append(
                    IndexQuote(
                        symbol=symbol,
                        name=name,
                        price=result["price"],
                        change=result["change"],
                        change_percent=result["change_percent"],
                        timestamp=result["timestamp"],
                    )
                )

        return indices

    async def get_sectors(self) -> List[SectorPerformance]:
        """Fetch sector performance via sector ETFs."""
        tasks = [self._fetch_quote_data(symbol) for symbol, _ in SECTOR_ETFS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        sectors = []
        for (symbol, sector), result in zip(SECTOR_ETFS, results):
            if isinstance(result, dict) and result:
                sectors.append(
                    SectorPerformance(
                        sector=sector,
                        symbol=symbol,
                        change_percent=result["change_percent"],
                        price=result["price"],
                        volume=result["volume"],
                    )
                )

        # Sort by change_percent descending
        sectors.sort(key=lambda x: x.change_percent, reverse=True)
        return sectors

    async def get_movers(
        self, limit: int = 5
    ) -> Tuple[List[MarketMover], List[MarketMover]]:
        """Fetch top gainers and losers from popular stocks."""
        tasks = []
        for symbol in POPULAR_STOCKS:
            tasks.append(self._fetch_with_name(symbol))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        movers = []
        for result in results:
            if isinstance(result, dict) and result and result.get("price"):
                movers.append(
                    MarketMover(
                        symbol=result["symbol"],
                        name=result["name"],
                        price=result["price"],
                        change=result["change"],
                        change_percent=result["change_percent"],
                        volume=result.get("volume"),
                    )
                )

        # Sort for gainers (highest change_percent) and losers (lowest)
        sorted_movers = sorted(movers, key=lambda x: x.change_percent, reverse=True)

        gainers = sorted_movers[:limit]
        losers = sorted_movers[-limit:][::-1]  # Reverse to show worst first

        return gainers, losers

    async def _fetch_with_name(self, symbol: str) -> Optional[dict]:
        """Fetch quote with name info."""
        try:
            quote = await self.yahoo.get_quote(symbol)
            info = await self.yahoo.get_info(symbol)
            if quote and info:
                return {
                    "symbol": symbol,
                    "name": info.get("shortName") or info.get("longName") or symbol,
                    "price": quote.price,
                    "change": quote.change,
                    "change_percent": quote.change_percent,
                    "volume": quote.volume,
                }
        except Exception as e:
            logger.warning(f"Failed to fetch {symbol}: {e}")
        return None

    async def get_currencies_commodities(self) -> List[CurrencyCommodity]:
        """Fetch currencies and commodities data."""
        tasks = [self._fetch_quote_data(symbol) for symbol, _, _ in CURRENCIES_COMMODITIES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        items = []
        for (symbol, name, category), result in zip(CURRENCIES_COMMODITIES, results):
            if isinstance(result, dict) and result:
                items.append(
                    CurrencyCommodity(
                        symbol=symbol,
                        name=name,
                        price=result["price"],
                        change=result["change"],
                        change_percent=result["change_percent"],
                        category=category,
                    )
                )

        return items

    async def get_market_overview(self) -> MarketOverviewResponse:
        """Fetch complete market overview data."""
        # Fetch all data concurrently
        indices_task = self.get_indices()
        sectors_task = self.get_sectors()
        movers_task = self.get_movers()
        cc_task = self.get_currencies_commodities()

        indices, sectors, (gainers, losers), currencies_commodities = await asyncio.gather(
            indices_task, sectors_task, movers_task, cc_task
        )

        return MarketOverviewResponse(
            indices=indices,
            sectors=sectors,
            gainers=gainers,
            losers=losers,
            currencies_commodities=currencies_commodities,
            timestamp=datetime.utcnow(),
        )


# Singleton instance
market_service = MarketService()
