"""Reconciliation service - builds the read-only §6 view for one account.

Strictly read-only. It compares the linked hash's latest-complete-run Schwab
positions against IC's per-account positions and open FIFO lots, and returns a
delta table. It writes nothing and adopts nothing - no mutation surface exists
here (that is the §2 next-wave work).

Gated only on an ACTIVE :class:`AccountLink` for the account (§6): quantity
reconciliation needs nothing beyond the link plus data that already exists, and
basis reconciliation adds only the open-lots helper (§3) - neither needs the
Trade-provenance columns or the adoption endpoint.
"""

from decimal import Decimal
from uuid import UUID

from app.db.models.broker_import import ImportedPosition
from app.schemas.reconciliation import (
    ReconciliationPosition,
    ReconciliationResponse,
)
from app.services import schwab_ingestion
from app.services.account_link import AccountLinkService
from app.services.trade import TradeService

_ELIGIBLE_ASSET_TYPE = "EQUITY"  # §5: v1 adoption eligibility


class ReconciliationService:
    def __init__(self, db) -> None:
        self.db = db
        self.links = AccountLinkService(db)
        self.trades = TradeService(db)

    async def build(
        self, user_id: UUID, account_id: int, source: str = "schwab_api"
    ) -> ReconciliationResponse | None:
        """The §6 envelope for ``account_id``, or ``None`` when the account has
        no active link (the caller maps that to 409).

        The caller is expected to have already 404'd an account that isn't the
        user's; this method only decides link-present vs link-absent.
        """
        link = await self.links.get_active_link(user_id, account_id, source)
        if link is None:
            return None

        account_hash = link.account_hash

        latest_complete = await schwab_ingestion.get_latest_complete_run(
            self.db, user_id, account_hash
        )
        last_import_at = (
            latest_complete.created_at if latest_complete is not None else None
        )
        never_imported = last_import_at is None
        newer_failed_import_at = await schwab_ingestion.get_newer_failed_import_at(
            self.db, user_id, account_hash
        )

        # Schwab side: latest complete run's rows ([] when never_imported).
        schwab_rows = await schwab_ingestion.get_current_positions(
            self.db, user_id, account_hash
        )
        schwab_by_symbol: dict[str, ImportedPosition] = {
            row.symbol: row for row in schwab_rows
        }

        # IC side: this account's positions (net qty + equity id per symbol).
        ic_positions = await self.trades._calculate_positions(
            user_id, with_quotes=False, by_account=True
        )
        ic_by_symbol = {
            p.equity.symbol: p
            for p in ic_positions
            if p.account_id == account_id
        }

        positions = []
        # Deterministic row order: union of symbols, sorted.
        for symbol in sorted(set(schwab_by_symbol) | set(ic_by_symbol)):
            sp = schwab_by_symbol.get(symbol)
            ip = ic_by_symbol.get(symbol)

            asset_type = sp.asset_type if sp is not None else None
            eligible = True if sp is None else asset_type == _ELIGIBLE_ASSET_TYPE
            ineligible_reason = (
                None if eligible else f"asset_type {asset_type} not supported"
            )

            schwab_quantity = sp.quantity if sp is not None else None
            ic_quantity = ip.quantity if ip is not None else None
            quantity_delta = (
                (schwab_quantity if schwab_quantity is not None else Decimal("0"))
                - (ic_quantity if ic_quantity is not None else Decimal("0"))
            )

            schwab_basis = sp.average_price if sp is not None else None
            ic_basis: Decimal | None = None
            ledger_inconsistent = False
            if ip is not None:
                open_lots = await self.trades._get_open_lots(
                    user_id, ip.equity_id, account_id
                )
                ledger_inconsistent = open_lots.ledger_inconsistent
                ic_basis = open_lots.basis()

            basis_delta = (
                schwab_basis - ic_basis
                if schwab_basis is not None and ic_basis is not None
                else None
            )

            positions.append(
                ReconciliationPosition(
                    symbol=symbol,
                    asset_type=asset_type,
                    eligible=eligible,
                    ineligible_reason=ineligible_reason,
                    schwab_quantity=schwab_quantity,
                    ic_quantity=ic_quantity,
                    quantity_delta=quantity_delta,
                    schwab_basis=schwab_basis,
                    ic_basis=ic_basis,
                    basis_delta=basis_delta,
                    ledger_inconsistent=ledger_inconsistent,
                )
            )

        return ReconciliationResponse(
            last_import_at=last_import_at,
            never_imported=never_imported,
            newer_failed_import_at=newer_failed_import_at,
            positions=positions,
        )
