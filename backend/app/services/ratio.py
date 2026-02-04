"""Ratio service - business logic for ratio operations."""

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ratio import Ratio
from app.schemas.ratio import (
    RatioCreate,
    RatioDataPoint,
    RatioHistoryResponse,
    RatioQuoteResponse,
    RatioResponse,
    RatioUpdate,
)
from app.services.data_providers.yahoo import YahooFinanceProvider

logger = logging.getLogger(__name__)


# Pre-defined system ratios
SYSTEM_RATIOS = [
    {
        "name": "Gold/Silver",
        "numerator_symbol": "GC=F",
        "denominator_symbol": "SI=F",
        "description": "Gold vs silver relative performance. Rising = gold outperforming silver. Falling = silver gaining on gold.",
        "category": "commodity",
    },
    {
        "name": "Gold/Bitcoin",
        "numerator_symbol": "GC=F",
        "denominator_symbol": "BTC-USD",
        "description": "Price of gold divided by Bitcoin. Falling = Bitcoin outperforming gold as store of value.",
        "category": "crypto",
    },
    {
        "name": "SPY/QQQ",
        "numerator_symbol": "SPY",
        "denominator_symbol": "QQQ",
        "description": "S&P 500 vs Nasdaq 100. Rising = broad market outperforming tech. Falling = tech leadership.",
        "category": "equity",
    },
    {
        "name": "Value/Growth",
        "numerator_symbol": "VTV",
        "denominator_symbol": "VUG",
        "description": "Rising = value stocks outperforming growth. Falling = growth leading (often in low-rate environments).",
        "category": "equity",
    },
    {
        "name": "Copper/Gold",
        "numerator_symbol": "HG=F",
        "denominator_symbol": "GC=F",
        "description": "Dr. Copper vs safe haven gold. Rising = economic optimism. Falling = risk-off/recession fears.",
        "category": "macro",
    },
    {
        "name": "TLT/IEF",
        "numerator_symbol": "TLT",
        "denominator_symbol": "IEF",
        "description": "Long bonds vs intermediate. Rising = curve steepening. Falling = flattening/inversion risk.",
        "category": "macro",
    },
    {
        "name": "Small Cap/Large Cap",
        "numerator_symbol": "IWM",
        "denominator_symbol": "SPY",
        "description": "Rising = small caps leading (risk-on, broadening rally). Falling = flight to large cap quality.",
        "category": "equity",
    },
    {
        "name": "EM/US",
        "numerator_symbol": "VWO",
        "denominator_symbol": "VTI",
        "description": "Rising = emerging markets outperforming US. Often correlates with weak dollar periods.",
        "category": "equity",
    },
]


class RatioService:
    """Service for ratio-related operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.yahoo = YahooFinanceProvider()

    async def initialize_system_ratios(self) -> None:
        """Create system ratios if they don't exist."""
        for ratio_data in SYSTEM_RATIOS:
            # Check if exists
            stmt = select(Ratio).where(
                Ratio.numerator_symbol == ratio_data["numerator_symbol"],
                Ratio.denominator_symbol == ratio_data["denominator_symbol"],
                Ratio.is_system == True,
            )
            result = await self.db.execute(stmt)
            existing = result.scalar_one_or_none()

            if not existing:
                ratio = Ratio(
                    name=ratio_data["name"],
                    numerator_symbol=ratio_data["numerator_symbol"],
                    denominator_symbol=ratio_data["denominator_symbol"],
                    description=ratio_data["description"],
                    category=ratio_data["category"],
                    is_system=True,
                    is_favorite=False,
                )
                self.db.add(ratio)

        await self.db.commit()

    async def list_ratios(
        self, favorites_only: bool = False, category: Optional[str] = None
    ) -> List[RatioResponse]:
        """List all ratios, optionally filtered."""
        stmt = select(Ratio)

        if favorites_only:
            stmt = stmt.where(Ratio.is_favorite == True)

        if category:
            stmt = stmt.where(Ratio.category == category)

        stmt = stmt.order_by(Ratio.is_favorite.desc(), Ratio.name)
        result = await self.db.execute(stmt)
        ratios = result.scalars().all()

        return [RatioResponse.model_validate(r) for r in ratios]

    async def get_ratio(self, ratio_id: int) -> Optional[RatioResponse]:
        """Get a single ratio by ID."""
        stmt = select(Ratio).where(Ratio.id == ratio_id)
        result = await self.db.execute(stmt)
        ratio = result.scalar_one_or_none()

        if ratio:
            return RatioResponse.model_validate(ratio)
        return None

    async def create_ratio(self, data: RatioCreate) -> RatioResponse:
        """Create a new custom ratio."""
        ratio = Ratio(
            name=data.name,
            numerator_symbol=data.numerator_symbol.upper(),
            denominator_symbol=data.denominator_symbol.upper(),
            description=data.description,
            category=data.category,
            is_system=False,
            is_favorite=data.is_favorite,
        )
        self.db.add(ratio)
        await self.db.commit()
        await self.db.refresh(ratio)

        return RatioResponse.model_validate(ratio)

    async def update_ratio(
        self, ratio_id: int, data: RatioUpdate
    ) -> Optional[RatioResponse]:
        """Update a ratio (only certain fields for system ratios)."""
        stmt = select(Ratio).where(Ratio.id == ratio_id)
        result = await self.db.execute(stmt)
        ratio = result.scalar_one_or_none()

        if not ratio:
            return None

        # For system ratios, only allow updating is_favorite
        if ratio.is_system:
            if data.is_favorite is not None:
                ratio.is_favorite = data.is_favorite
        else:
            # Custom ratios can update more fields
            if data.name is not None:
                ratio.name = data.name
            if data.description is not None:
                ratio.description = data.description
            if data.is_favorite is not None:
                ratio.is_favorite = data.is_favorite

        await self.db.commit()
        await self.db.refresh(ratio)

        return RatioResponse.model_validate(ratio)

    async def delete_ratio(self, ratio_id: int) -> bool:
        """Delete a custom ratio (cannot delete system ratios)."""
        stmt = select(Ratio).where(Ratio.id == ratio_id, Ratio.is_system == False)
        result = await self.db.execute(stmt)
        ratio = result.scalar_one_or_none()

        if not ratio:
            return False

        await self.db.delete(ratio)
        await self.db.commit()
        return True

    async def get_ratio_history(
        self, ratio_id: int, period: str = "1y"
    ) -> Optional[RatioHistoryResponse]:
        """Get historical ratio values."""
        ratio = await self.get_ratio(ratio_id)
        if not ratio:
            return None

        # Fetch history for both symbols
        num_history = await self.yahoo.get_history(ratio.numerator_symbol, period)
        den_history = await self.yahoo.get_history(ratio.denominator_symbol, period)

        if not num_history or not den_history:
            return RatioHistoryResponse(
                ratio=ratio,
                history=[],
                current_value=None,
            )

        # Build timestamp index from denominator
        den_index = {h.timestamp.date(): h for h in den_history}

        # Calculate ratio for each matching date
        history = []
        for num_point in num_history:
            date = num_point.timestamp.date()
            if date in den_index:
                den_point = den_index[date]
                if den_point.close and den_point.close != 0:
                    ratio_value = num_point.close / den_point.close
                    history.append(
                        RatioDataPoint(
                            timestamp=num_point.timestamp,
                            numerator_close=num_point.close,
                            denominator_close=den_point.close,
                            ratio_value=ratio_value,
                        )
                    )

        # Calculate changes
        current_value = history[-1].ratio_value if history else None
        change_1d = None
        change_1w = None
        change_1m = None

        if len(history) >= 2:
            change_1d = current_value - history[-2].ratio_value

        if len(history) >= 6:
            change_1w = current_value - history[-6].ratio_value

        if len(history) >= 22:
            change_1m = current_value - history[-22].ratio_value

        return RatioHistoryResponse(
            ratio=ratio,
            history=history,
            current_value=current_value,
            change_1d=change_1d,
            change_1w=change_1w,
            change_1m=change_1m,
        )

    async def get_ratio_quote(self, ratio_id: int) -> Optional[RatioQuoteResponse]:
        """Get current ratio quote."""
        stmt = select(Ratio).where(Ratio.id == ratio_id)
        result = await self.db.execute(stmt)
        ratio = result.scalar_one_or_none()

        if not ratio:
            return None

        # Fetch current quotes
        num_quote, den_quote = await asyncio.gather(
            self.yahoo.get_quote(ratio.numerator_symbol),
            self.yahoo.get_quote(ratio.denominator_symbol),
        )

        if not num_quote or not den_quote or den_quote.price == 0:
            return None

        current_value = num_quote.price / den_quote.price

        # Calculate daily change
        change_1d = None
        change_percent_1d = None

        if num_quote.previous_close and den_quote.previous_close and den_quote.previous_close != 0:
            prev_ratio = num_quote.previous_close / den_quote.previous_close
            change_1d = current_value - prev_ratio
            if prev_ratio != 0:
                change_percent_1d = (change_1d / prev_ratio) * 100

        return RatioQuoteResponse(
            id=ratio.id,
            name=ratio.name,
            numerator_symbol=ratio.numerator_symbol,
            denominator_symbol=ratio.denominator_symbol,
            current_value=current_value,
            change_1d=change_1d,
            change_percent_1d=change_percent_1d,
            timestamp=datetime.utcnow(),
        )

    async def get_all_ratio_quotes(self) -> List[RatioQuoteResponse]:
        """Get quotes for all ratios."""
        ratios = await self.list_ratios()
        tasks = [self.get_ratio_quote(r.id) for r in ratios]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        quotes = []
        for result in results:
            if isinstance(result, RatioQuoteResponse):
                quotes.append(result)

        return quotes
