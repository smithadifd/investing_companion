"""Trade-related Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.trade import TradeType
from app.schemas.account import AccountRef


class TradeEquity(BaseModel):
    """Embedded equity info in trade response."""

    id: int
    symbol: str
    name: str
    exchange: str | None = None
    sector: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TradeBase(BaseModel):
    """Base fields for trades."""

    trade_type: TradeType
    quantity: Decimal = Field(..., gt=0, description="Number of shares/units")
    price: Decimal = Field(..., gt=0, description="Price per share/unit")
    fees: Decimal = Field(default=Decimal("0"), ge=0, description="Transaction fees")
    executed_at: datetime = Field(..., description="When the trade was executed")
    notes: str | None = Field(None, max_length=5000)


class TradeCreate(TradeBase):
    """Schema for creating a trade."""

    equity_id: int | None = Field(None, description="ID of existing equity")
    symbol: str | None = Field(None, description="Symbol to look up if equity_id not provided")
    watchlist_item_id: int | None = Field(None, description="Link to watchlist thesis")
    account_id: int | None = Field(
        None, description="Account this trade belongs to (null = unassigned)"
    )

    @field_validator("symbol", "equity_id")
    @classmethod
    def require_equity_or_symbol(cls, v, info):
        """Ensure at least one of equity_id or symbol is provided."""
        # This runs for each field; full validation happens in the endpoint
        return v


class TradeUpdate(BaseModel):
    """Schema for updating a trade."""

    trade_type: TradeType | None = None
    quantity: Decimal | None = Field(None, gt=0)
    price: Decimal | None = Field(None, gt=0)
    fees: Decimal | None = Field(None, ge=0)
    executed_at: datetime | None = None
    notes: str | None = Field(None, max_length=5000)
    watchlist_item_id: int | None = None
    account_id: int | None = Field(
        None, description="Reassign to an account (explicit null unassigns)"
    )


class TradeResponse(TradeBase):
    """Schema for trade in responses."""

    id: int
    user_id: UUID
    equity_id: int
    watchlist_item_id: int | None = None
    account_id: int | None = None
    account: AccountRef | None = None
    equity: TradeEquity
    total_value: Decimal
    total_cost: Decimal
    position_closed: bool = Field(
        False,
        description=(
            "True when this trade zeroed out the position - set on create "
            "only, to drive the lesson-capture prompt"
        ),
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TradePairResponse(BaseModel):
    """Schema for trade pair (matched open/close)."""

    id: int
    equity_id: int
    open_trade_id: int
    close_trade_id: int
    quantity_matched: Decimal
    realized_pnl: Decimal
    holding_period_days: int
    calculated_at: datetime
    equity: TradeEquity

    model_config = ConfigDict(from_attributes=True)


class PositionSummary(BaseModel):
    """Current position in an equity (optionally scoped to one account)."""

    equity_id: int
    equity: TradeEquity
    account_id: int | None = Field(
        None, description="Set on per-account positions; null = aggregate or unassigned"
    )
    account: AccountRef | None = Field(
        None, description="Account context on per-account positions"
    )
    quantity: Decimal = Field(..., description="Net shares held (can be negative for short)")
    avg_cost_basis: Decimal = Field(..., description="Average cost per share")
    total_cost: Decimal = Field(..., description="Total invested")
    current_price: Decimal | None = Field(None, description="Latest price")
    current_value: Decimal | None = Field(None, description="Current market value")
    unrealized_pnl: Decimal | None = Field(None, description="Unrealized P&L")
    unrealized_pnl_percent: Decimal | None = Field(None, description="Unrealized P&L %")
    realized_pnl: Decimal = Field(default=Decimal("0"), description="Realized P&L from closed trades")
    first_trade_at: datetime
    last_trade_at: datetime


class PortfolioSummary(BaseModel):
    """Overall portfolio summary."""

    total_invested: Decimal
    current_value: Decimal | None = None
    total_unrealized_pnl: Decimal | None = None
    total_realized_pnl: Decimal
    positions: list[PositionSummary]
    position_count: int
    total_trades: int


class PerformanceMetrics(BaseModel):
    """Trading performance analytics."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal = Field(..., description="Win rate as decimal (0.55 = 55%)")
    total_realized_pnl: Decimal
    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    largest_win: Decimal | None = None
    largest_loss: Decimal | None = None
    profit_factor: Decimal | None = Field(None, description="Gross profit / Gross loss")
    average_holding_days: Decimal | None = None
    current_streak: int = Field(..., description="Positive = winning streak, negative = losing")
    longest_winning_streak: int
    longest_losing_streak: int


class PerformanceByCategory(BaseModel):
    """Performance breakdown by category."""

    category: str
    total_trades: int
    realized_pnl: Decimal
    win_rate: Decimal


class PerformanceReport(BaseModel):
    """Complete performance report."""

    metrics: PerformanceMetrics
    by_sector: list[PerformanceByCategory]
    by_equity: list[PerformanceByCategory]
    period_start: datetime | None = None
    period_end: datetime | None = None


class PositionSizeRequest(BaseModel):
    """Request for position size calculation."""

    account_size: Decimal = Field(..., gt=0, description="Total account value")
    risk_percent: Decimal = Field(..., gt=0, le=100, description="Risk percentage (1-100)")
    entry_price: Decimal = Field(..., gt=0, description="Planned entry price")
    stop_loss: Decimal = Field(..., gt=0, description="Stop loss price")
    method: str = Field(default="fixed_risk", description="Calculation method")


class PositionSizeResponse(BaseModel):
    """Position size calculation result."""

    shares: int = Field(..., description="Suggested number of shares")
    position_value: Decimal = Field(..., description="Total position value")
    risk_amount: Decimal = Field(..., description="Dollar amount at risk")
    risk_per_share: Decimal = Field(..., description="Risk per share")
    method: str
    notes: str | None = None


class TradeListFilters(BaseModel):
    """Filters for trade list queries."""

    equity_id: int | None = None
    symbol: str | None = None
    trade_type: TradeType | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None
