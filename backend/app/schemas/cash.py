"""Cash-ledger and NAV schemas (total-return design, Surfaces 2 and 4)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models.trade import CASH_LEDGER_TRADE_TYPES, TradeType
from app.schemas.account import AccountRef

_CASH_KIND_NAMES = " / ".join(k.value for k in CASH_LEDGER_TRADE_TYPES)


class CashTransactionBase(BaseModel):
    """Fields common to a cash-ledger write and read.

    ``kind`` is typed as the whole :class:`TradeType` because the column
    genuinely reuses ``trade_type_enum``; the validator below is what narrows
    it to the two cash members. Doing it this way (rather than a separate
    Python enum) keeps one vocabulary across the schema and makes the narrowing
    an explicit, testable rule instead of an implicit one.
    """

    kind: TradeType = Field(..., description=f"{_CASH_KIND_NAMES}")
    amount: Decimal = Field(
        ..., gt=0, description="Unsigned magnitude; direction is carried by `kind`"
    )
    occurred_at: datetime = Field(..., description="When the cash moved")
    notes: str | None = Field(None, max_length=5000)

    @model_validator(mode="after")
    def check_kind_is_cash(self) -> "CashTransactionBase":
        if self.kind not in CASH_LEDGER_TRADE_TYPES:
            raise ValueError(
                f"kind must be one of {_CASH_KIND_NAMES}; {self.kind.value!r} is a "
                "trade type and belongs in `trades`."
            )
        return self


class CashTransactionCreate(CashTransactionBase):
    """Schema for recording a deposit or withdrawal."""

    account_id: int = Field(
        ..., description="Account the cash moved into or out of (required)"
    )


class CashTransactionResponse(CashTransactionBase):
    """Schema for a cash transaction in responses.

    Deliberately NOT re-validated through :meth:`check_kind_is_cash` in a way
    that could break reads: the rule holds on the write path and at the DB
    (``ck_cash_transactions_kind_is_cash``), so a stored row cannot violate it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: UUID
    account_id: int
    account: AccountRef | None = None
    signed_amount: Decimal = Field(
        ..., description="+amount for a deposit, -amount for a withdrawal"
    )
    source: str = "manual"
    source_import_run_id: int | None = None
    external_transaction_id: str | None = None
    created_at: datetime
    updated_at: datetime


class CashCoverageMember(BaseModel):
    """One account's own completeness answer inside a scope.

    Completeness is a PER-ACCOUNT property; a scope is complete only if every
    member is. Reporting the scope as one flat verdict was the bug: an account
    with no import provenance simply did not appear in the fold, so a
    well-covered account could vouch for a sibling with an obvious history gap.

    ``account_id`` is null for the **unassigned trade bucket** - trades with no
    account. They still consume cash from the whole-ledger fold and nothing
    funds them, so they are a member in their own right rather than a silent
    omission.
    """

    account_id: int | None = Field(
        None, description="null = the unassigned trade bucket"
    )
    account_name: str | None = None
    is_known: bool = Field(
        ..., description="Whether THIS account's cash history can be shown complete"
    )
    cash_starts_at: datetime | None = None
    first_activity_at: datetime | None = None
    complete_from: datetime | None = Field(
        None, description="Earliest window a broker import delivered for this account"
    )
    has_history_gap: bool = Field(
        False,
        description=(
            "A pull was clamped to the broker's history horizon and no later "
            "pull reached back past it"
        ),
    )
    reason: str | None = Field(
        None, description="Why this account is not known; null when it is"
    )


class CashCoverage(BaseModel):
    """How far back the cash ledger actually knows this scope's history.

    The honest answer to Q-E. Schwab's transactions endpoint reaches only 60
    days back and has no pagination past that boundary, so a backfill can
    establish the ledger from there forward and *cannot* establish what the
    balance was before it. Rather than invent an opening balance - the exact
    fabrication ``plans/investing_companion/trade-readiness-card.md`` refused -
    NAV reports what it knows and flags what it does not.

    ``cash_starts_at`` (a row date) and ``complete_from`` (an import window)
    answer DIFFERENT questions, and conflating them was a real bug: "there is
    cash before the first trade" is not "the cash history is complete". See
    ``CashLedgerService.coverage``.
    """

    cash_starts_at: datetime | None = Field(
        None, description="Earliest recorded cash movement; null = no cash rows at all"
    )
    first_activity_at: datetime | None = Field(
        None, description="Earliest trade in scope; null = no activity at all"
    )
    complete_from: datetime | None = Field(
        None,
        description=(
            "Earliest instant cash movements are known COMPLETE from — the "
            "earliest window a broker import actually delivered. Null = no "
            "import provenance (a purely manual ledger)"
        ),
    )
    is_true_origin: bool = Field(
        False,
        description=(
            "DERIVED at read time, never stored: true only when EVERY account "
            "in scope has an import window that was unclamped and reached back "
            "past all of that account's trades. Never asserted by a clamped pull"
        ),
    )
    provenance_source: str | None = Field(
        None, description="Which lane established `complete_from` (e.g. schwab_api)"
    )
    provenance_note: str | None = Field(
        None,
        description="The import run's HISTORY GAP note — why `is_true_origin` is False",
    )
    opening_balance_is_known: bool = Field(
        ...,
        description=(
            "The scope's verdict: true only when EVERY member in `members` is "
            "individually known. False when any account has no cash rows, has "
            "trades predating its first cash row, or carries a broker import "
            "whose window was clamped short of its start"
        ),
    )
    members: list[CashCoverageMember] = Field(
        default_factory=list,
        description=(
            "Per-account detail. The scope's verdict is a fold over this list, "
            "so an unknown member always names itself"
        ),
    )


class NavSummary(BaseModel):
    """Total-return / NAV view for one account, or for the whole user ledger.

    Return methodology is the ABSOLUTE DOLLAR figure (Q-A, ratified):
    ``total_return_amount`` is unambiguous and is a correct answer to "did this
    account make money". ``total_return_percent`` divided by net contributions
    is NOT a time-weighted return and reads oddly when a large deposit lands
    late in the period, so it is offered as a secondary line and is null when
    contributions are zero. TWR and XIRR are deliberately out of scope for this
    cut.
    """

    account_id: int | None = Field(
        None, description="null = the whole user ledger (all accounts + unassigned)"
    )
    account: AccountRef | None = None

    cash_balance: Decimal = Field(..., description="The cash fold")
    positions_market_value: Decimal = Field(
        ..., description="Sum of current_value over open positions in scope"
    )
    nav: Decimal = Field(..., description="cash_balance + positions_market_value")

    net_contributions: Decimal = Field(
        ..., description="Sum of deposits - sum of withdrawals"
    )
    realized_pnl: Decimal = Field(
        ..., description="Sum of trade_pairs.realized_pnl in scope (already net of fees)"
    )
    unrealized_pnl: Decimal = Field(
        ...,
        description=(
            "Mark-to-market over the still-open FIFO lots, net of their "
            "unamortised opening fees. This is NOT the Positions tab's figure "
            "and will differ from it after a profitable partial sale — that "
            "one derives its basis from a net running cost, which counts the "
            "realised gain a second time. See NavService._unrealized_from_lots"
        ),
    )
    dividends_received: Decimal = Field(
        ..., description="Dividend cash actually received (already net of withholding)"
    )
    fees_paid: Decimal = Field(
        ...,
        description=(
            "Every commission and withholding charged in scope. REPORTED ONLY "
            "— total_return_amount does not subtract it, because realized_pnl "
            "and unrealized_pnl are both already net of fees"
        ),
    )
    total_return_amount: Decimal = Field(
        ...,
        description=(
            "realized + unrealized + dividends, in absolute dollars. The three "
            "terms are disjoint by construction"
        ),
    )
    total_return_percent: Decimal | None = Field(
        None,
        description=(
            "total_return_amount / net_contributions x 100. Null when net "
            "contributions are zero or negative. NOT time-weighted"
        ),
    )

    as_of: datetime
    is_estimated: bool = Field(
        ...,
        description="True when any input below is missing — never a silent zero",
    )
    estimate_reasons: list[str] = Field(
        default_factory=list,
        description="One entry per missing input; empty iff is_estimated is False",
    )
    coverage: CashCoverage


class CashBackfillSkipped(BaseModel):
    """One broker row the backfill declined to adopt, and why.

    Listed, never silently dropped — the promise
    ``schemas/reconciliation.py`` already makes for the ``non_trade`` lane.
    """

    external_transaction_id: str
    broker_type: str
    occurred_at: datetime
    net_amount: Decimal | None = None
    reason: str


class CashBackfillResult(BaseModel):
    """What one backfill pass over already-ingested broker rows did."""

    account_id: int
    created: list[CashTransactionResponse] = Field(default_factory=list)
    already_present: int = Field(
        0, description="Broker rows already adopted on an earlier pass (idempotent)"
    )
    skipped: list[CashBackfillSkipped] = Field(default_factory=list)
    coverage: CashCoverage
    history_gap_note: str | None = Field(
        None,
        description=(
            "Carried through from the import run when its requested window "
            "predated Schwab's 60-day history horizon — the span before it is "
            "unrecoverable via the API"
        ),
    )
    transaction_history_limit_days: int
