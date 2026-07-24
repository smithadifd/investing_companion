"""Account API endpoints - brokerage accounts for multi-account positions."""


from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.account import AccountCreate, AccountResponse, AccountUpdate
from app.schemas.account_link import AccountLinkCreate, AccountLinkResponse
from app.schemas.common import DataResponse, ResponseMeta
from app.schemas.reconciliation import ReconciliationResponse
from app.services.account import AccountService
from app.services.account_link import (
    AccountLinkService,
    AccountNotFoundError,
    LinkNeedsConfirmationError,
)
from app.services.reconciliation import ReconciliationService

router = APIRouter()


def get_account_service(db: AsyncSession = Depends(get_db)) -> AccountService:
    """Dependency to get account service instance."""
    return AccountService(db)


def get_account_link_service(
    db: AsyncSession = Depends(get_db),
) -> AccountLinkService:
    """Dependency to get the AccountLink service instance."""
    return AccountLinkService(db)


def get_reconciliation_service(
    db: AsyncSession = Depends(get_db),
) -> ReconciliationService:
    """Dependency to get the reconciliation service instance."""
    return ReconciliationService(db)


@router.get("", response_model=DataResponse[list[AccountResponse]])
async def list_accounts(
    current_user: User = Depends(get_current_user),
    service: AccountService = Depends(get_account_service),
) -> DataResponse[list[AccountResponse]]:
    """List the user's accounts, ordered by display_order."""
    accounts = await service.list_accounts(current_user.id)
    return DataResponse(data=accounts, meta=ResponseMeta.now())


@router.post(
    "", response_model=DataResponse[AccountResponse], status_code=status.HTTP_201_CREATED
)
async def create_account(
    data: AccountCreate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: AccountService = Depends(get_account_service),
) -> DataResponse[AccountResponse]:
    """Create an account (e.g. Roth, taxable, 401k)."""
    try:
        account = await service.create_account(current_user.id, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return DataResponse(data=account, meta=ResponseMeta.now())


@router.get("/{account_id}", response_model=DataResponse[AccountResponse])
async def get_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    service: AccountService = Depends(get_account_service),
) -> DataResponse[AccountResponse]:
    """Get a single account by ID."""
    account = await service.get_account(account_id, current_user.id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        )
    return DataResponse(data=account, meta=ResponseMeta.now())


@router.put("/{account_id}", response_model=DataResponse[AccountResponse])
async def update_account(
    account_id: int,
    data: AccountUpdate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: AccountService = Depends(get_account_service),
) -> DataResponse[AccountResponse]:
    """Update an account. Explicit nulls clear broker/type/risk fields."""
    try:
        account = await service.update_account(account_id, current_user.id, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        )
    return DataResponse(data=account, meta=ResponseMeta.now())


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: AccountService = Depends(get_account_service),
) -> None:
    """Delete an account. Its trades become unassigned (FK SET NULL)."""
    deleted = await service.delete_account(account_id, current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        )


# ---------------------------------------------------------------------------
# Schwab account links (§1/§4) + read-only reconciliation view (§6)
# ---------------------------------------------------------------------------
@router.get(
    "/{account_id}/links",
    response_model=DataResponse[list[AccountLinkResponse]],
)
async def list_account_links(
    account_id: int,
    current_user: User = Depends(get_current_user),
    service: AccountLinkService = Depends(get_account_link_service),
) -> DataResponse[list[AccountLinkResponse]]:
    """List broker links (active + orphaned) for this account. Read-only."""
    links = await service.list_links(current_user.id, account_id)
    return DataResponse(data=links, meta=ResponseMeta.now())


@router.post(
    "/{account_id}/links",
    response_model=DataResponse[AccountLinkResponse],
    status_code=status.HTTP_201_CREATED,
)
async def link_account(
    account_id: int,
    data: AccountLinkCreate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: AccountLinkService = Depends(get_account_link_service),
) -> DataResponse[AccountLinkResponse]:
    """Link a broker ``account_hash`` to this account (status active, §4).

    A hash rotation orphans the prior active link in the same transaction.
    Linking to an account that already has trades needs ``confirm=true`` (409
    until then) - those trades become the reconciliation baseline.
    """
    try:
        link = await service.link_account(
            current_user.id,
            account_id,
            data.account_hash,
            source=data.source,
            confirm=data.confirm,
        )
    except AccountNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        )
    except LinkNeedsConfirmationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return DataResponse(data=link, meta=ResponseMeta.now())


@router.get(
    "/{account_id}/reconciliation",
    response_model=DataResponse[ReconciliationResponse],
)
async def get_account_reconciliation(
    account_id: int,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
    service: ReconciliationService = Depends(get_reconciliation_service),
) -> DataResponse[ReconciliationResponse]:
    """Read-only §6 reconciliation view: Schwab-vs-IC deltas for this account.

    Gated ONLY on an active AccountLink existing (§6). No demo guard - this is
    a read endpoint (a demo user may see what adoption *would* do, never
    execute it). Strictly read-only: no Adopt surface, writes nothing.
    """
    account = await account_service.get_account(account_id, current_user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        )
    result = await service.build(current_user.id, account_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Account has no active Schwab link; link a Schwab account to "
                "reconcile."
            ),
        )
    return DataResponse(data=result, meta=ResponseMeta.now())
