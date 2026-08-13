"""Broker import trigger - the user-facing "pull from Schwab now" action.

``schwab_ingestion`` landed the pull primitives (T2 sub-PR 1) and
``reconciliation``/``adoption`` landed the compare + adopt layers (sub-PR 2),
but until this module nothing in the running application ever CALLED
:func:`~app.services.schwab_ingestion.pull_positions` or
:func:`~app.services.schwab_ingestion.pull_transactions` - they were reachable
only from tests. The reconciliation view could therefore never leave its
``never_imported`` state in a deployed instance. This is that missing arm: it
resolves the account's active :class:`AccountLink` to a Schwab account hash and
invokes the pulls for it.

SESSION OWNERSHIP (the contract this module exists to respect): the two pull
functions own their entire transactional lifecycle and must NEVER be handed a
caller's session - see ``schwab_ingestion``'s module docstring. So this service
uses its request-scoped ``db`` for exactly one thing, a read: resolving the
active link. It then calls each pull with NO session argument, letting the
ingestion module build its own session from the application sessionmaker. A
``session_factory`` may be passed through for tests only, and is forwarded
verbatim - this module never opens, commits, or rolls back a session itself.

ATOMICITY: each pull is one all-or-nothing transaction inside the ingestion
module, and the two kinds are independent. A positions pull that succeeds is
kept even if the transactions pull then fails; the failure is reported per-kind
in the response (and durably as a ``status=failed``
:class:`~app.db.models.broker_import.BrokerImportRun`) rather than unwinding
work that did land. Nothing here spans the two pulls in one transaction, which
is deliberate: there is no shared invariant between a positions snapshot and a
transactions window that a partial success could violate.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.broker_import import BrokerImportRun, ImportKind
from app.schemas.broker_import import ImportKindRequest, ImportRunSummary
from app.services import schwab_ingestion
from app.services.account_link import AccountLinkService
from app.services.data_providers.schwab import SchwabAPIError, SchwabAuthError
from app.services.schwab_ingestion import SchwabNotConnectedError

logger = logging.getLogger(__name__)


class NoActiveLinkError(Exception):
    """The account has no active broker link, so there is no hash to pull for."""


class BrokerImportService:
    """Triggers Schwab pulls for one linked account."""

    def __init__(self, db: AsyncSession) -> None:
        # Read-only use: resolving the active link. Never handed to a pull.
        self.db = db
        self.links = AccountLinkService(db)

    async def trigger(
        self,
        user_id: UUID,
        account_id: int,
        kind: ImportKindRequest = ImportKindRequest.BOTH,
        source: str = "schwab_api",
        *,
        session_factory: Callable[[], AsyncSession] | None = None,
    ) -> list[ImportRunSummary]:
        """Pull ``kind`` for the account's linked hash; one summary per pull.

        The caller is expected to have already 404'd an account that isn't this
        user's; this method only decides link-present vs link-absent (raising
        :class:`NoActiveLinkError`, which the caller maps to 409).

        Cross-user isolation: ``user_id`` is the AUTHENTICATED user throughout.
        The hash is resolved from that user's own active link
        (``AccountLinkService.get_active_link`` filters on ``user_id``), and the
        same ``user_id`` is then passed to the pulls, which stamp it onto every
        run/position/transaction row they write. There is no path by which one
        user's request can pull into, or read, another user's rows.

        Errors from the provider are NOT swallowed - they propagate so the
        endpoint can distinguish "reconnect Schwab" from "Schwab said no" - but
        a failure of one kind never discards an earlier kind that succeeded
        (see the module docstring's ATOMICITY note).
        """
        link = await self.links.get_active_link(user_id, account_id, source)
        if link is None:
            raise NoActiveLinkError()
        account_hash = link.account_hash

        kinds: list[ImportKind] = []
        if kind in (ImportKindRequest.POSITIONS, ImportKindRequest.BOTH):
            kinds.append(ImportKind.POSITIONS)
        if kind in (ImportKindRequest.TRANSACTIONS, ImportKindRequest.BOTH):
            kinds.append(ImportKind.TRANSACTIONS)

        summaries: list[ImportRunSummary] = []
        for one_kind in kinds:
            run = await self._pull(
                user_id, account_hash, one_kind, session_factory=session_factory
            )
            summaries.append(ImportRunSummary.model_validate(run))
        return summaries

    async def _pull(
        self,
        user_id: UUID,
        account_hash: str,
        kind: ImportKind,
        *,
        session_factory: Callable[[], AsyncSession] | None = None,
    ) -> BrokerImportRun:
        """One pull of ``kind``, with NO caller session (session ownership)."""
        fn = (
            schwab_ingestion.pull_positions
            if kind == ImportKind.POSITIONS
            else schwab_ingestion.pull_transactions
        )
        # session_factory is forwarded, never defaulted here: passing None lets
        # schwab_ingestion pick the application sessionmaker itself, which is
        # the production path. Tests inject an engine-bound factory.
        if session_factory is None:
            return await fn(user_id, account_hash)
        return await fn(user_id, account_hash, session_factory=session_factory)


__all__ = [
    "BrokerImportService",
    "NoActiveLinkError",
    "SchwabAPIError",
    "SchwabAuthError",
    "SchwabNotConnectedError",
]
