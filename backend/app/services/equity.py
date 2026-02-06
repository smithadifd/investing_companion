"""Equity service - business logic for equity operations."""

from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.equity import Equity
from app.schemas.equity import (
    EquityDetailResponse,
    EquitySearchResult,
    FundamentalsResponse,
    HistoryResponse,
    QuoteResponse,
)
from app.services.cache import cache_service
from app.services.data_providers.yahoo import YahooFinanceProvider


class EquityService:
    """Service for equity-related operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.yahoo = YahooFinanceProvider()

    async def search(self, query: str, limit: int = 20) -> List[EquitySearchResult]:
        """Search equities - first check DB, then external provider."""
        # Check database first (if available)
        try:
            stmt = (
                select(Equity)
                .where(
                    or_(
                        Equity.symbol.ilike(f"%{query}%"),
                        Equity.name.ilike(f"%{query}%"),
                    )
                )
                .limit(limit)
            )
            result = await self.db.execute(stmt)
            db_results = [
                EquitySearchResult.model_validate(e) for e in result.scalars().all()
            ]

            if db_results:
                return db_results
        except Exception:
            # Database not available, fall through to external provider
            pass

        # Fall back to Yahoo Finance
        return await self.yahoo.search(query, limit)

    async def get_quote(self, symbol: str) -> Optional[QuoteResponse]:
        """Get quote with caching."""
        cache_key = cache_service.quote_key(symbol)

        # Check cache (if Redis available)
        try:
            cached = await cache_service.get(cache_key)
            if cached:
                return QuoteResponse(**cached)
        except Exception:
            pass  # Cache not available

        # Fetch from provider
        quote = await self.yahoo.get_quote(symbol)
        if quote:
            try:
                await cache_service.set(
                    cache_key,
                    quote.model_dump(),
                    settings.QUOTE_CACHE_TTL,
                )
            except Exception:
                pass  # Cache not available

        return quote

    async def get_history(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> Optional[HistoryResponse]:
        """Get historical data with caching."""
        cache_key = cache_service.history_key(symbol, period, interval)

        # Check cache (if Redis available)
        try:
            cached = await cache_service.get(cache_key)
            if cached:
                return HistoryResponse(**cached)
        except Exception:
            pass  # Cache not available

        # Fetch from provider
        history = await self.yahoo.get_history(symbol, period, interval)
        if history:
            response = HistoryResponse(
                symbol=symbol.upper(),
                interval=interval,
                history=history,
            )
            try:
                await cache_service.set(
                    cache_key,
                    response.model_dump(),
                    settings.HISTORY_CACHE_TTL,
                )
            except Exception:
                pass  # Cache not available
            return response

        return None

    async def get_fundamentals(self, symbol: str) -> Optional[FundamentalsResponse]:
        """Get fundamentals with caching."""
        cache_key = cache_service.fundamentals_key(symbol)

        # Check cache (if Redis available)
        try:
            cached = await cache_service.get(cache_key)
            if cached:
                return FundamentalsResponse(**cached)
        except Exception:
            pass  # Cache not available

        # Fetch from provider
        fundamentals = await self.yahoo.get_fundamentals(symbol)
        if fundamentals:
            try:
                await cache_service.set(
                    cache_key,
                    fundamentals.model_dump(),
                    settings.FUNDAMENTALS_CACHE_TTL,
                )
            except Exception:
                pass  # Cache not available

        return fundamentals

    async def get_or_create_equity(self, symbol: str) -> Optional[Equity]:
        """Get equity from DB or create from provider data."""
        import logging
        logger = logging.getLogger(__name__)

        try:
            stmt = select(Equity).where(Equity.symbol == symbol.upper())
            result = await self.db.execute(stmt)
            equity = result.scalar_one_or_none()

            if equity:
                logger.info(f"Found existing equity: {equity.symbol}")
                return equity

            # Fetch from Yahoo and create
            logger.info(f"Fetching equity info from Yahoo for: {symbol}")
            info = await self.yahoo.get_info(symbol)
            if not info or not info.get("symbol"):
                logger.warning(f"No info found for symbol: {symbol}")
                return None

            equity = Equity(
                symbol=info["symbol"].upper(),
                name=info.get("longName") or info.get("shortName") or symbol,
                exchange=info.get("exchange"),
                asset_type=(info.get("quoteType") or "stock").lower(),
                sector=info.get("sector"),
                industry=info.get("industry"),
                country=info.get("country") or "US",
                currency=info.get("currency") or "USD",
            )
            self.db.add(equity)
            await self.db.commit()
            await self.db.refresh(equity)

            logger.info(f"Created new equity: {equity.symbol}")
            return equity
        except Exception as e:
            logger.error(f"Error in get_or_create_equity for {symbol}: {e}")
            # Database not available, return None
            return None

    async def get_equity_detail(self, symbol: str) -> Optional[EquityDetailResponse]:
        """Get full equity details including quote and fundamentals."""
        # Try to get or create equity from database
        equity = await self.get_or_create_equity(symbol)

        # Fetch quote and fundamentals (works without DB)
        quote = await self.get_quote(symbol)
        fundamentals = await self.get_fundamentals(symbol)

        if equity:
            return EquityDetailResponse(
                symbol=equity.symbol,
                name=equity.name,
                exchange=equity.exchange,
                asset_type=equity.asset_type,
                sector=equity.sector,
                industry=equity.industry,
                country=equity.country,
                currency=equity.currency,
                quote=quote,
                fundamentals=fundamentals,
            )

        # Fallback: build response from Yahoo data if DB unavailable
        if quote:
            info = await self.yahoo.get_info(symbol)
            return EquityDetailResponse(
                symbol=symbol.upper(),
                name=info.get("longName") or info.get("shortName") or symbol if info else symbol,
                exchange=info.get("exchange") if info else None,
                asset_type=(info.get("quoteType") or "stock").lower() if info else "stock",
                sector=info.get("sector") if info else None,
                industry=info.get("industry") if info else None,
                country=info.get("country") or "US" if info else "US",
                currency=info.get("currency") or "USD" if info else "USD",
                quote=quote,
                fundamentals=fundamentals,
            )

        return None

    async def get_peers(self, symbol: str, limit: int = 5) -> List[EquityDetailResponse]:
        """Get peer companies in the same sector for comparison."""
        import logging
        logger = logging.getLogger(__name__)

        # First get the target equity's sector
        equity = await self.get_or_create_equity(symbol)
        if not equity or not equity.sector:
            logger.info(f"No sector found for {symbol}, trying external peer lookup")
            # Try to get sector from Yahoo
            info = await self.yahoo.get_info(symbol)
            sector = info.get("sector") if info else None
            if sector:
                return await self.get_sector_peers_external(symbol, sector, limit)
            return []

        # Find other equities in the same sector from the database
        try:
            stmt = (
                select(Equity)
                .where(
                    Equity.sector == equity.sector,
                    Equity.symbol != symbol.upper(),
                    Equity.is_active.is_(True),
                )
                .limit(limit)
            )
            result = await self.db.execute(stmt)
            peer_equities = result.scalars().all()

            # If we don't have enough in DB, use external data
            if len(peer_equities) < limit:
                return await self.get_sector_peers_external(symbol, equity.sector, limit)

            # Get full details for each peer
            peers = []
            for peer in peer_equities:
                detail = await self.get_equity_detail(peer.symbol)
                if detail:
                    peers.append(detail)

            return peers
        except Exception as e:
            logger.error(f"Error fetching peers for {symbol}: {e}")
            return await self.get_sector_peers_external(symbol, equity.sector, limit)

    async def get_sector_peers_external(
        self, symbol: str, sector: str, limit: int = 5
    ) -> List[EquityDetailResponse]:
        """Get peer companies using external data (common sector constituents)."""
        import logging
        logger = logging.getLogger(__name__)

        # Common sector stocks for peer discovery
        SECTOR_STOCKS = {
            "Technology": ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO", "ORCL", "CRM", "AMD", "INTC"],
            "Healthcare": ["UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY"],
            "Financial Services": ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "AXP", "C"],
            "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "TJX", "LOW", "BKNG", "CMG"],
            "Communication Services": ["GOOGL", "META", "NFLX", "DIS", "CMCSA", "VZ", "T", "TMUS", "CHTR", "EA"],
            "Industrials": ["UNP", "HON", "UPS", "BA", "CAT", "RTX", "DE", "LMT", "GE", "MMM"],
            "Consumer Defensive": ["PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL", "MDLZ", "KHC"],
            "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PXD", "VLO", "PSX", "OXY"],
            "Utilities": ["NEE", "DUK", "SO", "D", "SRE", "AEP", "EXC", "XEL", "ED", "WEC"],
            "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "PSA", "O", "SPG", "WELL", "DLR", "AVB"],
            "Basic Materials": ["LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "DOW", "DD", "PPG"],
        }

        peers = []
        symbols_to_check = SECTOR_STOCKS.get(sector, [])

        # Filter out the current symbol and limit
        symbols_to_check = [s for s in symbols_to_check if s.upper() != symbol.upper()][:limit]

        for peer_symbol in symbols_to_check:
            try:
                detail = await self.get_equity_detail(peer_symbol)
                if detail:
                    peers.append(detail)
            except Exception as e:
                logger.warning(f"Failed to fetch peer {peer_symbol}: {e}")
                continue

        return peers
