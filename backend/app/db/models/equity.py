"""Equity model - core entity for stocks, ETFs, and other securities."""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.fundamentals import EquityFundamentals
    from app.db.models.price_history import PriceHistory


class Equity(Base, TimestampMixin):
    """Primary entity for stocks, ETFs, and other securities."""

    __tablename__ = "equities"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[Optional[str]] = mapped_column(String(50))
    asset_type: Mapped[str] = mapped_column(String(20), default="stock", nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    industry: Mapped[Optional[str]] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(50), default="US", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    fundamentals: Mapped[Optional["EquityFundamentals"]] = relationship(
        back_populates="equity",
        uselist=False,
        lazy="selectin",
    )
    price_history: Mapped[List["PriceHistory"]] = relationship(
        back_populates="equity",
        lazy="dynamic",
    )

    __table_args__ = (
        Index("idx_equities_symbol", "symbol"),
        Index("idx_equities_sector", "sector"),
        Index("idx_equities_asset_type", "asset_type"),
    )

    def __repr__(self) -> str:
        return f"<Equity(symbol={self.symbol}, name={self.name})>"
