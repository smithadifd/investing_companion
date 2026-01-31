"""PriceHistory model - OHLCV data stored in TimescaleDB hypertable."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.equity import Equity


class PriceHistory(Base):
    """TimescaleDB hypertable for OHLCV data.

    Note: After creating this table via Alembic migration, run:
    SELECT create_hypertable('price_history', 'timestamp', if_not_exists => TRUE);
    """

    __tablename__ = "price_history"

    equity_id: Mapped[int] = mapped_column(
        ForeignKey("equities.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    open: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    adj_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6))
    volume: Mapped[Optional[int]] = mapped_column(BigInteger)

    # Relationship
    equity: Mapped["Equity"] = relationship(back_populates="price_history")

    __table_args__ = (
        PrimaryKeyConstraint("equity_id", "timestamp"),
        Index("idx_price_history_equity_time", "equity_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<PriceHistory(equity_id={self.equity_id}, timestamp={self.timestamp})>"
