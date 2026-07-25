"""Adoption service - the §2 mutation that turns a reconciliation delta into
synthetic, provenance-stamped Trades.

This is the write-side counterpart to the read-only §6 reconciliation view. It
computes the exact same per-symbol deltas the view shows (by reusing
``ReconciliationService``, so "what you see is what you adopt"), then for each
eligible, non-zero, non-crossing row writes ONE synthetic BUY/SELL sized to the
delta through ``TradeService.create_trade`` (the shared commit path, §2
"Transaction boundaries").

Binding v1 scope (schwab-adopt-semantics.md §2/§3/§5):
  * BUY (delta > 0) or SELL (delta < 0) only - never SHORT/COVER.
  * A negative Schwab quantity, or a reconciliation that would cross zero (IC
    currently short), is flagged "manual review needed", never auto-adopted.
  * Only asset_type == "EQUITY" (or an IC-only row) is eligible (§5).
  * The synthetic trade is priced at ``ImportedPosition.average_price``
    (Schwab's reported average); when Schwab reports no average, it falls back
    to the equity's current quote and sets ``basis_is_estimated=True`` (§3).
  * Replay/race-safe via the partial unique index on
    (user, account, equity, source_import_run_id) WHERE is_synthetic: a
    concurrent double-adopt raises IntegrityError, caught here as
    ``already_adopted`` (never a 500).

Per-row, not all-or-nothing: each equity commits independently, so one skip or
race never aborts the batch.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import Trade, TradeType
from app.schemas.adoption import AdoptedTrade, AdoptionResponse, SkippedPosition
from app.schemas.trade import TradeCreate
from app.services import schwab_ingestion
from app.services.account_link import AccountLinkService
from app.services.reconciliation import ReconciliationService
from app.services.trade import TradeService

_ELIGIBLE_ASSET_TYPE = "EQUITY"  # §5


class NoActiveLinkError(Exception):
    """The account has no active broker link - nothing to adopt against."""


class NeverImportedError(Exception):
    """The account is linked but has no completed Schwab import yet.

    Adopting here would treat every IC position as drift against an empty
    Schwab side and SELL it all to zero - exactly the "no pull yet, not no
    drift" trap §6 warns about. Refused (caller -> 409).
    """


class AdoptionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.links = AccountLinkService(db)
        self.reconciliation = ReconciliationService(db)
        self.trades = TradeService(db)
        self.equity_service = self.trades.equity_service

    async def adopt(
        self, user_id: UUID, account_id: int, source: str = "schwab_api"
    ) -> AdoptionResponse:
        """Adopt the account's latest-complete-run deltas into synthetic trades.

        The caller is expected to have already 404'd an account that isn't the
        user's. Raises :class:`NoActiveLinkError` (no active link) or
        :class:`NeverImportedError` (linked but never a complete pull) - both
        map to 409.
        """
        link = await self.links.get_active_link(user_id, account_id, source)
        if link is None:
            raise NoActiveLinkError()

        run = await schwab_ingestion.get_latest_complete_run(
            self.db, user_id, link.account_hash
        )
        if run is None:
            raise NeverImportedError()
        run_id = run.id

        # Same delta computation the §6 view renders (WYSIWYG). Inject the run
        # we just selected so the deltas are computed from the SAME run we stamp
        # onto every synthetic trade below - if a newer complete run lands
        # between here and the view's own query, we must not price/size against
        # run B while the idempotency key names run A.
        recon = await self.reconciliation.build(
            user_id, account_id, source, run=run
        )
        # recon is not None here: get_active_link already succeeded.

        adopted: list[AdoptedTrade] = []
        skipped: list[SkippedPosition] = []

        for row in recon.positions:
            delta = row.quantity_delta
            if delta == 0:
                continue  # matched - no-op, listed in neither bucket

            if not row.eligible:
                skipped.append(
                    SkippedPosition(
                        symbol=row.symbol,
                        quantity_delta=delta,
                        reason="ineligible",
                        detail=row.ineligible_reason or "asset class not supported",
                    )
                )
                continue

            cur = row.ic_quantity if row.ic_quantity is not None else Decimal("0")
            tgt = (
                row.schwab_quantity
                if row.schwab_quantity is not None
                else Decimal("0")
            )
            # v1 does BUY/SELL only. A negative Schwab quantity, or an IC side
            # that is itself short (reconciling would cross zero), can't be
            # expressed as a single BUY/SELL - flag for manual review (§2).
            if tgt < 0:
                skipped.append(
                    SkippedPosition(
                        symbol=row.symbol, quantity_delta=delta,
                        reason="manual_review",
                        detail=(
                            "Schwab reports a negative (short) quantity; v1 "
                            "adopts BUY/SELL only."
                        ),
                    )
                )
                continue
            if cur < 0:
                skipped.append(
                    SkippedPosition(
                        symbol=row.symbol, quantity_delta=delta,
                        reason="manual_review",
                        detail=(
                            "IC holds a short position; reconciling would cross "
                            "zero, which v1 (BUY/SELL only) does not adopt."
                        ),
                    )
                )
                continue

            # Basis source (§3): Schwab's reported average when present, else a
            # current-quote placeholder flagged estimated.
            basis_is_estimated = row.schwab_basis is None
            price = row.schwab_basis
            if price is None:
                quote = await self.equity_service.get_quote(row.symbol)
                price = quote.price if quote and quote.price else None
            if price is None or price <= 0:
                skipped.append(
                    SkippedPosition(
                        symbol=row.symbol, quantity_delta=delta,
                        reason="no_basis",
                        detail=(
                            "No Schwab average price and no current quote "
                            "available to price the synthetic trade."
                        ),
                    )
                )
                continue

            equity = await self.equity_service.get_or_create_equity(row.symbol)
            if equity is None:
                skipped.append(
                    SkippedPosition(
                        symbol=row.symbol, quantity_delta=delta,
                        reason="unresolved_equity",
                        detail="Could not resolve or create the equity.",
                    )
                )
                continue

            trade_type = TradeType.BUY if delta > 0 else TradeType.SELL
            quantity = abs(delta)

            result = await self._adopt_one(
                user_id=user_id,
                account_id=account_id,
                equity_id=equity.id,
                symbol=row.symbol,
                trade_type=trade_type,
                quantity=quantity,
                price=price,
                basis_is_estimated=basis_is_estimated,
                source=source,
                source_import_run_id=run_id,
            )
            adopted.append(result)

        return AdoptionResponse(
            account_id=account_id,
            source_import_run_id=run_id,
            adopted=adopted,
            skipped=skipped,
        )

    async def _adopt_one(
        self,
        *,
        user_id: UUID,
        account_id: int,
        equity_id: int,
        symbol: str,
        trade_type: TradeType,
        quantity: Decimal,
        price: Decimal,
        basis_is_estimated: bool,
        source: str,
        source_import_run_id: int,
    ) -> AdoptedTrade:
        """Write one synthetic trade, idempotent on the partial unique index.

        A concurrent adopt that committed first for this (account, equity, run)
        makes ``create_trade``'s commit raise IntegrityError; we roll back and
        report the existing trade as ``already_adopted`` rather than 500.
        """
        data = TradeCreate(
            equity_id=equity_id,
            trade_type=trade_type,
            quantity=quantity,
            price=price,
            fees=Decimal("0"),
            executed_at=datetime.now(timezone.utc),
            account_id=account_id,
        )
        try:
            created = await self.trades.create_trade(
                user_id,
                data,
                source=source,
                is_synthetic=True,
                basis_is_estimated=basis_is_estimated,
                source_import_run_id=source_import_run_id,
            )
        except IntegrityError:
            await self.db.rollback()
            existing_id = await self._existing_synthetic_id(
                user_id, account_id, equity_id, source_import_run_id
            )
            # Only the partial-unique-index collision (a synthetic row already
            # exists for this exact key) is the replay-safe "already adopted"
            # case. Any OTHER IntegrityError - an FK violation, a NOT NULL, a
            # different constraint - is a genuine failure and must NOT be
            # dressed up as replay success (which would also carry a null
            # trade_id). Re-raise it so it surfaces as a 500 for the real cause.
            if existing_id is None:
                raise
            return AdoptedTrade(
                symbol=symbol,
                equity_id=equity_id,
                trade_type=trade_type.value,
                quantity=quantity,
                price=None,
                basis_is_estimated=basis_is_estimated,
                status="already_adopted",
                trade_id=existing_id,
            )

        return AdoptedTrade(
            symbol=symbol,
            equity_id=equity_id,
            trade_type=trade_type.value,
            quantity=quantity,
            price=price,
            basis_is_estimated=basis_is_estimated,
            status="created",
            trade_id=created.id if created is not None else None,
        )

    async def _existing_synthetic_id(
        self,
        user_id: UUID,
        account_id: int,
        equity_id: int,
        source_import_run_id: int,
    ) -> int | None:
        return await self.db.scalar(
            select(Trade.id).where(
                Trade.user_id == user_id,
                Trade.account_id == account_id,
                Trade.equity_id == equity_id,
                Trade.source_import_run_id == source_import_run_id,
                Trade.is_synthetic.is_(True),
            )
        )
