"""Cash-ledger API endpoints (total-return design, Surface 2 + Q-E).

Deliberately a small surface: list, record, delete, backfill. There is no
update verb - a cash movement is a fact with four fields, and correcting one is
a delete plus a re-record, which keeps the broker-adopted rows' idempotency key
meaning exactly one thing.

Endpoints stay thin per AGENTS.md's layering rule; every decision lives in
``services/cash.py`` and ``services/cash_backfill.py``.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.cash import (
    CashBackfillResult,
    CashTransactionCreate,
    CashTransactionResponse,
)
from app.schemas.common import (
    DataResponse,
    ListResponse,
    PaginatedMeta,
    ResponseMeta,
)
from app.services.cash import CashLedgerService
from app.services.cash_backfill import CashBackfillService

router = APIRouter()


def get_cash_service(db: AsyncSession = Depends(get_db)) -> CashLedgerService:
    """Dependency to get the cash-ledger service instance."""
    return CashLedgerService(db)


def get_backfill_service(db: AsyncSession = Depends(get_db)) -> CashBackfillService:
    """Dependency to get the broker cash-backfill service instance."""
    return CashBackfillService(db)


@router.get("", response_model=ListResponse[CashTransactionResponse])
async def list_cash_transactions(
    account_id: int | None = Query(None, description="Filter by account ID"),
    limit: int = Query(100, ge=1, le=500, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    current_user: User = Depends(get_current_user),
    service: CashLedgerService = Depends(get_cash_service),
) -> ListResponse[CashTransactionResponse]:
    """
    List cash transactions (deposits and withdrawals) for the authenticated user.

    Ordered by when the cash moved, newest first. `amount` is always an
    unsigned magnitude; `signed_amount` carries the direction.
    """
    rows, total = await service.list_transactions(
        user_id=current_user.id, account_id=account_id, limit=limit, offset=offset
    )
    meta = PaginatedMeta(
        total=total,
        page=offset // limit + 1,
        per_page=limit,
        pages=max(1, -(-total // limit)),
    )
    return ListResponse(data=rows, meta=meta)


@router.post(
    "",
    response_model=DataResponse[CashTransactionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_cash_transaction(
    data: CashTransactionCreate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: CashLedgerService = Depends(get_cash_service),
) -> DataResponse[CashTransactionResponse]:
    """
    Record a deposit or withdrawal against one of your accounts.

    `account_id` is required: cash that belongs to no account has no meaning
    and no NAV can be built over it. `kind` must be `deposit` or `withdrawal`.
    """
    row = await service.create_transaction(current_user.id, data)

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not record cash transaction. Account not found.",
        )

    return DataResponse(data=row, meta=ResponseMeta.now())


@router.post("/backfill", response_model=DataResponse[CashBackfillResult])
async def backfill_cash_from_broker(
    account_id: int = Query(..., description="Account to backfill"),
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: CashBackfillService = Depends(get_backfill_service),
) -> DataResponse[CashBackfillResult]:
    """
    Adopt already-imported broker cash movements into the cash ledger.

    Reads the transactions the Schwab sync has already pulled — this makes no
    network call and touches no token. Idempotent: re-running adopts nothing
    new, it just reports what was already there.

    Only external cash movements (ACH/wire/cash receipts and disbursements) are
    adopted. Dividends are manual entry, journals are internal transfers, and
    an unrecognised broker type is listed in `skipped` rather than guessed at —
    nothing is silently dropped.

    `history_gap_note` is set when the import ran up against Schwab's 60-day
    history horizon: the ledger's start is a boundary, not the beginning of the
    account, and NAV reads `is_estimated` before it.

    409 when the account has no active broker link; 404 when it is not yours.
    """
    result = await service.backfill(current_user.id, account_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Account not found, or it has no active broker link to backfill "
                "from. Link it under Settings first."
            ),
        )

    return DataResponse(data=result, meta=ResponseMeta.now())


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cash_transaction(
    transaction_id: int,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: CashLedgerService = Depends(get_cash_service),
) -> None:
    """Delete a cash transaction. 404 when it is not yours."""
    if not await service.delete_transaction(transaction_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cash transaction not found",
        )
