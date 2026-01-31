"""EquityFundamentals model - cached fundamental data for equities."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.equity import Equity


class EquityFundamentals(Base):
    """One-to-one with Equity. Cached fundamental data."""

    __tablename__ = "equity_fundamentals"

    id: Mapped[int] = mapped_column(primary_key=True)
    equity_id: Mapped[int] = mapped_column(
        ForeignKey("equities.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # Valuation metrics
    market_cap: Mapped[Optional[int]] = mapped_column(BigInteger)
    enterprise_value: Mapped[Optional[int]] = mapped_column(BigInteger)
    pe_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    forward_pe: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    peg_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    price_to_book: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    price_to_sales: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))

    # Profitability
    eps_ttm: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    eps_forward: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    revenue_ttm: Mapped[Optional[int]] = mapped_column(BigInteger)
    net_income_ttm: Mapped[Optional[int]] = mapped_column(BigInteger)
    profit_margin: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    operating_margin: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    roe: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    roa: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))

    # Dividends
    dividend_yield: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    dividend_per_share: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    payout_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))

    # Trading
    beta: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    week_52_high: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    week_52_low: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    avg_volume_10d: Mapped[Optional[int]] = mapped_column(BigInteger)
    avg_volume_3m: Mapped[Optional[int]] = mapped_column(BigInteger)
    shares_outstanding: Mapped[Optional[int]] = mapped_column(BigInteger)
    float_shares: Mapped[Optional[int]] = mapped_column(BigInteger)
    short_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    # Metadata
    data_source: Mapped[Optional[str]] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationship
    equity: Mapped["Equity"] = relationship(back_populates="fundamentals")

    __table_args__ = (Index("idx_fundamentals_equity", "equity_id"),)

    def __repr__(self) -> str:
        return f"<EquityFundamentals(equity_id={self.equity_id})>"
