"""Equity service - business logic for equity operations."""

from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.equity import Equity
from app.db.models.fundamentals import EquityFundamentals
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
        # Check database first
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

        # Fall back to Yahoo Finance
        return await self.yahoo.search(query, limit)

    async def get_quote(self, symbol: str) -> Optional[QuoteResponse]:
        """Get quote with caching."""
        cache_key = cache_service.quote_key(symbol)

        # Check cache
        cached = await cache_service.get(cache_key)
        if cached:
            return QuoteResponse(**cached)

        # Fetch from provider
        quote = await self.yahoo.get_quote(symbol)
        if quote:
            await cache_service.set(
                cache_key,
                quote.model_dump(),
                settings.QUOTE_CACHE_TTL,
            )

        return quote

    async def get_history(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> Optional[HistoryResponse]:
        """Get historical data with caching."""
        cache_key = cache_service.history_key(symbol, period, interval)

        # Check cache
        cached = await cache_service.get(cache_key)
        if cached:
            return HistoryResponse(**cached)

        # Fetch from provider
        history = await self.yahoo.get_history(symbol, period, interval)
        if history:
            response = HistoryResponse(
                symbol=symbol.upper(),
                interval=interval,
                history=history,
            )
            await cache_service.set(
                cache_key,
                response.model_dump(),
                settings.HISTORY_CACHE_TTL,
            )
            return response

        return None

    async def get_fundamentals(self, symbol: str) -> Optional[FundamentalsResponse]:
        """Get fundamentals with caching."""
        cache_key = cache_service.fundamentals_key(symbol)

        # Check cache
        cached = await cache_service.get(cache_key)
        if cached:
            return FundamentalsResponse(**cached)

        # Fetch from provider
        fundamentals = await self.yahoo.get_fundamentals(symbol)
        if fundamentals:
            await cache_service.set(
                cache_key,
                fundamentals.model_dump(),
                settings.FUNDAMENTALS_CACHE_TTL,
            )

        return fundamentals

    async def get_or_create_equity(self, symbol: str) -> Optional[Equity]:
        """Get equity from DB or create from provider data."""
        stmt = select(Equity).where(Equity.symbol == symbol.upper())
        result = await self.db.execute(stmt)
        equity = result.scalar_one_or_none()

        if equity:
            return equity

        # Fetch from Yahoo and create
        info = await self.yahoo.get_info(symbol)
        if not info or not info.get("symbol"):
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

        return equity

    async def get_equity_detail(self, symbol: str) -> Optional[EquityDetailResponse]:
        """Get full equity details including quote and fundamentals."""
        # Get or create equity
        equity = await self.get_or_create_equity(symbol)
        if not equity:
            return None

        # Fetch quote and fundamentals
        quote = await self.get_quote(symbol)
        fundamentals = await self.get_fundamentals(symbol)

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
