"""Account API endpoints - brokerage accounts for multi-account positions."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.account import AccountCreate, AccountResponse, AccountUpdate
from app.schemas.common import DataResponse, ResponseMeta
from app.services.account import AccountService

router = APIRouter()


def get_account_service(db: AsyncSession = Depends(get_db)) -> AccountService:
    """Dependency to get account service instance."""
    return AccountService(db)


@router.get("", response_model=DataResponse[List[AccountResponse]])
async def list_accounts(
    current_user: User = Depends(get_current_user),
    service: AccountService = Depends(get_account_service),
) -> DataResponse[List[AccountResponse]]:
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
