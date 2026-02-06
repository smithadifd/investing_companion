"""Economic event models for calendar and earnings tracking."""

import uuid
from datetime import date, time
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.equity import Equity
    from app.db.models.user import User


class EventType(str, Enum):
    """Types of economic events."""

    # Equity-specific events
    EARNINGS = "earnings"
    EX_DIVIDEND = "ex_dividend"
    DIVIDEND_PAY = "dividend_pay"
    STOCK_SPLIT = "stock_split"

    # Macro economic events
    FOMC = "fomc"
    CPI = "cpi"
    PPI = "ppi"
    NFP = "nfp"  # Non-Farm Payrolls (Jobs Report)
    GDP = "gdp"
    PCE = "pce"  # Personal Consumption Expenditures
    RETAIL_SALES = "retail_sales"
    UNEMPLOYMENT = "unemployment"
    ISM_MANUFACTURING = "ism_manufacturing"
    ISM_SERVICES = "ism_services"
    HOUSING_STARTS = "housing_starts"
    CONSUMER_CONFIDENCE = "consumer_confidence"

    # User-defined
    CUSTOM = "custom"
    IPO = "ipo"


class EventImportance(str, Enum):
    """Importance level of events."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EventSource(str, Enum):
    """Source of event data."""

    YAHOO = "yahoo"
    MANUAL = "manual"
    SEED = "seed"
    ALPHA_VANTAGE = "alpha_vantage"


class EconomicEvent(Base, TimestampMixin):
    """Model for economic and corporate events."""

    __tablename__ = "economic_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Event classification
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Optional link to equity (for earnings, dividends, splits)
    equity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equities.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Optional link to user (for custom events)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Timing
    event_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    event_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Event details
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # For economic releases (actual/forecast/previous values)
    actual_value: Mapped[Optional[float]] = mapped_column(
        Numeric(precision=20, scale=4), nullable=True
    )
    forecast_value: Mapped[Optional[float]] = mapped_column(
        Numeric(precision=20, scale=4), nullable=True
    )
    previous_value: Mapped[Optional[float]] = mapped_column(
        Numeric(precision=20, scale=4), nullable=True
    )

    # Metadata
    importance: Mapped[str] = mapped_column(
        String(10), default=EventImportance.MEDIUM.value, nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(50), default=EventSource.MANUAL.value, nullable=False
    )
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # For recurring events, store the recurrence pattern
    recurrence_key: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )  # e.g., "fomc_2025_01", "earnings_AAPL_2025Q1"

    # Relationships
    equity: Mapped[Optional["Equity"]] = relationship("Equity", lazy="selectin")
    user: Mapped[Optional["User"]] = relationship("User", lazy="selectin")

    __table_args__ = (
        Index("idx_economic_events_date", "event_date"),
        Index("idx_economic_events_type", "event_type"),
        Index("idx_economic_events_equity_id", "equity_id"),
        Index("idx_economic_events_user_id", "user_id"),
        Index("idx_economic_events_date_type", "event_date", "event_type"),
        # Prevent duplicate events for same equity on same date with same type
        UniqueConstraint(
            "equity_id",
            "event_type",
            "event_date",
            name="uq_equity_event_date",
        ),
        # Prevent duplicate macro events on same date
        Index(
            "idx_economic_events_recurrence",
            "recurrence_key",
            unique=True,
            postgresql_where="recurrence_key IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        equity_str = f", equity_id={self.equity_id}" if self.equity_id else ""
        return f"<EconomicEvent(id={self.id}, type={self.event_type}, date={self.event_date}{equity_str})>"

    @property
    def is_equity_event(self) -> bool:
        """Check if this is an equity-specific event."""
        return self.event_type in [
            EventType.EARNINGS.value,
            EventType.EX_DIVIDEND.value,
            EventType.DIVIDEND_PAY.value,
            EventType.STOCK_SPLIT.value,
        ]

    @property
    def is_macro_event(self) -> bool:
        """Check if this is a macro economic event."""
        return self.event_type in [
            EventType.FOMC.value,
            EventType.CPI.value,
            EventType.PPI.value,
            EventType.NFP.value,
            EventType.GDP.value,
            EventType.PCE.value,
            EventType.RETAIL_SALES.value,
            EventType.UNEMPLOYMENT.value,
            EventType.ISM_MANUFACTURING.value,
            EventType.ISM_SERVICES.value,
            EventType.HOUSING_STARTS.value,
            EventType.CONSUMER_CONFIDENCE.value,
        ]
