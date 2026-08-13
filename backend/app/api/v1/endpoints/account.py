"""Account API endpoints - brokerage accounts for multi-account positions."""


from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.account import AccountCreate, AccountResponse, AccountUpdate
from app.schemas.account_link import AccountLinkCreate, AccountLinkResponse
from app.schemas.adoption import AdoptionResponse
from app.schemas.broker_import import (
    CsvImportRequest,
    CsvImportResponse,
    ImportTriggerRequest,
    ImportTriggerResponse,
)
from app.schemas.common import DataResponse, ResponseMeta
from app.schemas.reconciliation import (
    ReconciliationResponse,
    TransactionReconciliationResponse,
)
from app.services.account import AccountService
from app.services.account_link import (
    AccountLinkService,
    AccountNotFoundError,
    LinkNeedsConfirmationError,
)
from app.services.adoption import (
    AdoptionService,
    NeverImportedError,
    NoActiveLinkError,
)
from app.services.broker_csv import (
    BrokerCsvImportService,
    CsvFormatError,
)
from app.services.broker_csv import (
    NoActiveLinkError as CsvNoActiveLinkError,
)
from app.services.broker_import import BrokerImportService
from app.services.broker_import import (
    NoActiveLinkError as ImportNoActiveLinkError,
)
from app.services.data_providers.schwab import SchwabAPIError, SchwabAuthError
from app.services.reconciliation import ReconciliationService
from app.services.schwab_ingestion import SchwabNotConnectedError

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


def get_adoption_service(
    db: AsyncSession = Depends(get_db),
) -> AdoptionService:
    """Dependency to get the adoption service instance."""
    return AdoptionService(db)


def get_broker_import_service(
    db: AsyncSession = Depends(get_db),
) -> BrokerImportService:
    """Dependency to get the broker import (pull trigger) service instance."""
    return BrokerImportService(db)


def get_broker_csv_service(
    db: AsyncSession = Depends(get_db),
) -> BrokerCsvImportService:
    """Dependency to get the broker-CSV import service instance."""
    return BrokerCsvImportService(db)


async def _owned_account_or_404(
    account_id: int, user_id, account_service: AccountService
) -> None:
    """404 unless ``account_id`` belongs to ``user_id``.

    Cross-user isolation is enforced here, BEFORE any broker work: an account
    the caller does not own is indistinguishable from one that does not exist,
    so nothing downstream ever sees another user's account id, link, or hash.
    """
    if await account_service.get_account(account_id, user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        )


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


@router.post(
    "/{account_id}/import",
    response_model=DataResponse[ImportTriggerResponse],
    status_code=status.HTTP_201_CREATED,
)
async def trigger_broker_import(
    account_id: int,
    data: ImportTriggerRequest | None = None,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
    service: BrokerImportService = Depends(get_broker_import_service),
) -> DataResponse[ImportTriggerResponse]:
    """Pull positions and/or transactions from Schwab for this linked account.

    This is the trigger the ingestion primitives were built for: before it, the
    reconciliation view could never leave ``never_imported`` in a deployed
    instance because nothing called them outside tests.

    Mutation (it writes import runs and rows) - demo-guarded. Owner-scoped: 404
    for an account that isn't the caller's, checked before any hash is
    resolved. 409 when the account has no active Schwab link, or when Schwab
    isn't connected/the token has passed its 7-day expiry (both are "go
    reconnect", not server faults). 502 when Schwab itself rejects or fails the
    call - the pull already recorded a ``status=failed`` run, so the failure is
    durable and visible either way.
    """
    await _owned_account_or_404(account_id, current_user.id, account_service)
    payload = data or ImportTriggerRequest()
    try:
        runs = await service.trigger(
            current_user.id, account_id, payload.kind, payload.source
        )
    except ImportNoActiveLinkError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Account has no active Schwab link; link a Schwab account to "
                "import."
            ),
        )
    except SchwabNotConnectedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except (SchwabAuthError, SchwabAPIError) as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Schwab import failed: {e}",
        )
    return DataResponse(
        data=ImportTriggerResponse(account_id=account_id, runs=runs),
        meta=ResponseMeta.now(),
    )


@router.post(
    "/{account_id}/import/csv",
    response_model=DataResponse[CsvImportResponse],
    status_code=status.HTTP_201_CREATED,
)
async def import_broker_csv(
    account_id: int,
    data: CsvImportRequest,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
    service: BrokerCsvImportService = Depends(get_broker_csv_service),
) -> DataResponse[CsvImportResponse]:
    """Import a broker transaction CSV - the history recovery path (sub-PR 3).

    Schwab's API only serves the trailing 60 days of transactions and cannot
    paginate past that, so any older activity is permanently unreachable
    through the pull. A broker CSV export reaches as far back as the broker's
    own web export does, and lands in the same imported-transactions table
    (``source="csv_import"``) so recovered rows reconcile side by side with
    API-pulled ones.

    Mutation - demo-guarded. Owner-scoped: 404 for an account that isn't the
    caller's. 409 without an active broker link. 422 when the upload isn't a
    recognizable transaction CSV. Re-uploading the same export is idempotent.
    """
    await _owned_account_or_404(account_id, current_user.id, account_service)
    try:
        result = await service.import_csv(
            current_user.id,
            account_id,
            data.content,
            filename=data.filename,
            link_source=data.link_source,
        )
    except CsvNoActiveLinkError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Account has no active Schwab link; link a Schwab account "
                "before importing its history."
            ),
        )
    except CsvFormatError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    return DataResponse(data=result, meta=ResponseMeta.now())


@router.get(
    "/{account_id}/reconciliation/transactions",
    response_model=DataResponse[TransactionReconciliationResponse],
)
async def get_account_transaction_reconciliation(
    account_id: int,
    days: int = Query(
        90,
        ge=1,
        le=3650,
        description=(
            "Width of the reconciled window in days, ending now. Wider than "
            "Schwab's 60-day API horizon on purpose: CSV-recovered rows can "
            "sit arbitrarily far back."
        ),
    ),
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
    service: ReconciliationService = Depends(get_reconciliation_service),
) -> DataResponse[TransactionReconciliationResponse]:
    """Read-only activity reconciliation: broker transactions vs IC trades.

    The companion to the §6 positions view. Positions say how far off the
    ledger is in aggregate; this says which individual fills were never written
    down (``broker_only``) and which IC trades the broker doesn't report
    (``ic_only``). No demo guard - read-only, like the positions view.
    """
    await _owned_account_or_404(account_id, current_user.id, account_service)
    result = await service.build_transactions(current_user.id, account_id, days=days)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Account has no active Schwab link; link a Schwab account to "
                "reconcile."
            ),
        )
    return DataResponse(data=result, meta=ResponseMeta.now())


@router.post(
    "/{account_id}/reconciliation/adopt",
    response_model=DataResponse[AdoptionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def adopt_reconciliation(
    account_id: int,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
    service: AdoptionService = Depends(get_adoption_service),
) -> DataResponse[AdoptionResponse]:
    """§2 adoption: write synthetic, provenance-stamped Trades from the §6
    reconciliation delta for this account.

    Mutation - demo-guarded (403 in demo mode). Owner-scoped (404 for an
    account that isn't the user's). 409 when the account has no active Schwab
    link, or is linked but has no completed import yet (adopting against an
    empty Schwab side would sell every IC position to zero). Replay-safe: a
    re-adopt against the same run creates no duplicate (the delta is recomputed
    and the partial unique index enforces idempotency).
    """
    account = await account_service.get_account(account_id, current_user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        )
    try:
        result = await service.adopt(current_user.id, account_id)
    except NoActiveLinkError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Account has no active Schwab link; link a Schwab account to "
                "adopt."
            ),
        )
    except NeverImportedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Account is linked but has no completed Schwab import yet; "
                "nothing to adopt."
            ),
        )
    return DataResponse(data=result, meta=ResponseMeta.now())
