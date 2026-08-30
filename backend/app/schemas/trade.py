"""Trade-related Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models.trade import CASH_LEDGER_TRADE_TYPES, TradeType
from app.schemas.account import AccountRef


class TradeEquity(BaseModel):
    """Embedded equity info in trade response."""

    id: int
    symbol: str
    name: str
    exchange: str | None = None
    sector: str | None = None

    model_config = ConfigDict(from_attributes=True)


def validate_trade_shape(
    trade_type: TradeType,
    price: Decimal,
    account_id: int | None = None,
) -> None:
    """Reject a malformed (type, price, account) combination on a ``trades`` row.

    Raises ``ValueError`` (which pydantic wraps into a 422 at the schema layer,
    and which ``TradeService.update_trade`` already maps to 422 at the service
    layer). Three rules, all *tighter* than what shipped before, never looser:

    * ``deposit``/``withdrawal`` are not trades at all - they have no equity leg
      and belong in ``cash_transactions``.
    * a ``split`` row's ``price`` is the sentinel ``0`` (its ``quantity`` is the
      ratio: 4 for 4:1, 0.25 for a 1:4 reverse), and it carries **no account** -
      a split is a property of the security, so one row adjusts every account
      partition holding it (design doc, Surface 3 "Ordering and scope").
    * every other member keeps the old ``price > 0`` requirement. The DB column
      is deliberately not check-constrained (a zero basis is legitimate for a
      vested RSU or a gifted lot), so this is an API-layer rule only.

    WRITE-SIDE ONLY, deliberately. It is not attached to ``TradeBase``/
    ``TradeResponse``: a stored row that predates these rules (or that a seed,
    an importer or psql wrote around them) must stay *readable*. Attaching a
    shape rule to a response model makes one bad row break the whole list
    endpoint forever - the same failure ``reconciliation._finite`` exists to
    prevent.
    """
    if trade_type in CASH_LEDGER_TRADE_TYPES:
        raise ValueError(
            f"{trade_type.value!r} is not a trade type: it has no equity leg. "
            "Record it in the cash ledger (cash_transactions) instead."
        )
    if trade_type == TradeType.SPLIT:
        if price != 0:
            raise ValueError(
                "price must be 0 on a split row - the ratio is carried by "
                "quantity (4 for a 4:1, 0.25 for a 1:4 reverse)."
            )
        if account_id is not None:
            raise ValueError(
                "a split row must not carry an account_id: a split is a "
                "property of the security and adjusts every account holding it."
            )
    elif price <= 0:
        raise ValueError(f"price must be greater than 0 for a {trade_type.value} trade")


class TradeBase(BaseModel):
    """Base fields for trades.

    ``price`` is ``ge=0`` rather than ``gt=0`` because a ``split`` row's price
    is the sentinel zero; the per-type rule lives in
    :func:`validate_trade_shape`, which the write schemas apply. See that
    docstring for why it is not applied here.
    """

    trade_type: TradeType
    quantity: Decimal = Field(..., gt=0, description="Number of shares/units")
    price: Decimal = Field(
        ...,
        ge=0,
        description="Price per share/unit (0 only on a split row, where quantity is the ratio)",
    )
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

    @model_validator(mode="after")
    def check_trade_shape(self) -> "TradeCreate":
        validate_trade_shape(self.trade_type, self.price, self.account_id)
        return self


class TradeUpdate(BaseModel):
    """Schema for updating a trade.

    Every field is optional, so the (type, price, account) rules can only be
    checked against the *resulting* row - ``TradeService.update_trade`` calls
    :func:`validate_trade_shape` after applying the patch. ``price`` is ``ge=0``
    here for the same reason it is on :class:`TradeBase`.
    """

    trade_type: TradeType | None = None
    quantity: Decimal | None = Field(None, gt=0)
    price: Decimal | None = Field(None, ge=0)
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
    # Provenance / adoption fields (§2/§3). Read-only here - set by the
    # adoption endpoint, never accepted on the public create/update body.
    source: str = "manual"
    is_synthetic: bool = False
    basis_is_estimated: bool = False
    source_import_run_id: int | None = None
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
