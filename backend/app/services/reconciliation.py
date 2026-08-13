"""Reconciliation service - builds the read-only views for one account.

Strictly read-only, both of them. It writes nothing and adopts nothing - the
§2 adoption mutation lives in ``services/adoption.py`` and calls in here for
its deltas, so what a user sees is exactly what adoption would write.

* :meth:`ReconciliationService.build` - the §6 POSITIONS view: the linked
  hash's latest-complete-run Schwab positions against IC's per-account
  positions and open FIFO lots, as a delta table.
* :meth:`ReconciliationService.build_transactions` - the TRANSACTIONS activity
  view: imported broker transactions against IC's manually-entered trades, as
  matched / broker-only / IC-only rows. Positions reconciliation says *how far
  off* the ledger is; this says *which fills were never written down*, which is
  the thing a human can actually act on.

Both are gated only on an ACTIVE :class:`AccountLink` for the account (§6),
and both take the AUTHENTICATED ``user_id`` as their first argument and thread
it into every query - the link lookup, the imported-row reads, and the IC-side
trade reads are each filtered on it, so no query in this module can return a
row belonging to another user.

SESSION OWNERSHIP: this service only ever READS through the request-scoped
session it is constructed with. It never commits, never rolls back, and never
calls the ``schwab_ingestion`` pull functions (which own their own sessions) -
only that module's read helpers, which explicitly accept any caller session.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.broker_import import (
    BrokerImportRun,
    ImportedPosition,
    ImportedTransaction,
    ImportKind,
)
from app.db.models.trade import Trade, TradeType
from app.schemas.reconciliation import (
    ReconciliationPosition,
    ReconciliationResponse,
    TransactionMatch,
    TransactionReconciliationResponse,
)
from app.services import schwab_ingestion
from app.services.account_link import AccountLinkService
from app.services.trade import TradeService

_ELIGIBLE_ASSET_TYPE = "EQUITY"  # §5: v1 adoption eligibility

# How far apart a broker fill and an IC trade may be and still be considered
# the same event. Deliberately generous (whole days, not minutes): broker
# exports routinely carry a settlement or trade DATE with no time component,
# and a hand-entered IC trade carries whatever wall-clock the user typed. A
# tighter tolerance would report a symbol/side/quantity-identical pair as two
# separate rows - a false "you never wrote this down", which is the exact
# failure mode this view exists to avoid.
_MATCH_DATE_TOLERANCE_DAYS = 2

# Default width of the reconciled window when the caller names none.
_DEFAULT_TRANSACTION_VIEW_DAYS = 90


def _finite(value: Decimal | None) -> Decimal | None:
    """``None`` for a non-finite Decimal, else the value unchanged.

    Postgres ``numeric`` accepts NaN and Infinity, and pydantic refuses to
    serialize them - so a single such stored cell would make the view that
    reads it raise a ValidationError on EVERY subsequent read.

    APPLY THIS AT EVERY SITE THAT READS A STORED DECIMAL INTO A RESPONSE
    MODEL. The ingestion parsers (``schwab_ingestion._decimal``,
    ``broker_csv._decimal``) both reject non-finite values, but that is a
    guard on TODAY'S writers, not an invariant of the column: ``numeric``
    itself permits NaN, rows predate any guard, and a future writer (a
    backfill, a fixture, another broker lane) is not bound by it. Treat stored
    decimals as untrusted on read and this stays true no matter what lands in
    the table - which matters because deletions are out of scope for v1, so a
    row that breaks a view breaks it permanently.
    """
    if value is None or not value.is_finite():
        return None
    return value


class ReconciliationService:
    def __init__(self, db) -> None:
        self.db = db
        self.links = AccountLinkService(db)
        self.trades = TradeService(db)

    async def build(
        self,
        user_id: UUID,
        account_id: int,
        source: str = "schwab_api",
        *,
        run: BrokerImportRun | None = None,
    ) -> ReconciliationResponse | None:
        """The §6 envelope for ``account_id``, or ``None`` when the account has
        no active link (the caller maps that to 409).

        The caller is expected to have already 404'd an account that isn't the
        user's; this method only decides link-present vs link-absent.

        ``run`` lets the adoption caller inject the run it has already selected
        (and will stamp onto the synthetic trades), so the deltas rendered here
        are computed from *that same* run - no run-completes-mid-call window
        between "which run priced/sized the trade" and "which run the
        idempotency key names". When ``run`` is None (the read-only view), the
        latest complete run is selected once and used for BOTH ``last_import_at``
        and the position snapshot, so those can't drift apart either.
        """
        link = await self.links.get_active_link(user_id, account_id, source)
        if link is None:
            return None

        account_hash = link.account_hash

        if run is None:
            run = await schwab_ingestion.get_latest_complete_run(
                self.db, user_id, account_hash
            )
        last_import_at = run.created_at if run is not None else None
        never_imported = last_import_at is None
        newer_failed_import_at = await schwab_ingestion.get_newer_failed_import_at(
            self.db, user_id, account_hash
        )

        # Schwab side: the pinned run's rows ([] when never_imported).
        schwab_rows = (
            await schwab_ingestion.get_positions_for_run(self.db, run.id)
            if run is not None
            else []
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

            # _finite() BEFORE the arithmetic, not after: a non-finite stored
            # cell reads as absent (the same as "that side has no position"),
            # which keeps quantity_delta finite by construction and therefore
            # keeps the schema's "NEVER null" guarantee on it honest. Sanitizing
            # afterwards would leave a NaN delta with nowhere legal to put it.
            schwab_quantity = _finite(sp.quantity) if sp is not None else None
            ic_quantity = _finite(ip.quantity) if ip is not None else None
            quantity_delta = (
                (schwab_quantity if schwab_quantity is not None else Decimal("0"))
                - (ic_quantity if ic_quantity is not None else Decimal("0"))
            )

            schwab_basis = _finite(sp.average_price) if sp is not None else None
            ic_basis: Decimal | None = None
            ledger_inconsistent = False
            if ip is not None:
                open_lots = await self.trades._get_open_lots(
                    user_id, ip.equity_id, account_id
                )
                ledger_inconsistent = open_lots.ledger_inconsistent
                ic_basis = _finite(open_lots.basis())

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

    # -----------------------------------------------------------------
    # Transactions activity view
    # -----------------------------------------------------------------
    async def build_transactions(
        self,
        user_id: UUID,
        account_id: int,
        source: str = "schwab_api",
        *,
        days: int | None = None,
    ) -> TransactionReconciliationResponse | None:
        """Activity reconciliation for ``account_id``, or ``None`` when the
        account has no active link (the caller maps that to 409).

        The caller is expected to have already 404'd an account that isn't the
        user's; this method only decides link-present vs link-absent.

        ``source`` selects which LINK to resolve (the account's Schwab link),
        not which imported rows to read: transactions written by the CSV
        recovery path carry ``source="csv_import"`` but belong to the same
        broker account hash, and the entire point of that path is that they
        reconcile side by side with API-pulled rows. So the imported-row query
        below filters on ``(user_id, account_hash)`` and deliberately NOT on
        source; each row reports its own lane via ``broker_source``.

        Every query here is filtered on ``user_id`` - the link, the imported
        transactions, and the IC trades alike.
        """
        link = await self.links.get_active_link(user_id, account_id, source)
        if link is None:
            return None
        account_hash = link.account_hash

        window_end = datetime.now(timezone.utc)
        window_days = days if days is not None else _DEFAULT_TRANSACTION_VIEW_DAYS
        window_start = window_end - timedelta(days=window_days)

        run = await schwab_ingestion.get_latest_complete_run(
            self.db, user_id, account_hash, ImportKind.TRANSACTIONS
        )
        last_import_at = run.created_at if run is not None else None
        newer_failed_import_at = await schwab_ingestion.get_newer_failed_import_at(
            self.db, user_id, account_hash, ImportKind.TRANSACTIONS
        )
        # A clamped, API-unrecoverable span on the LATEST complete transactions
        # run. Reading only the latest run is what makes this self-clearing: a
        # subsequent CSV import writes its own complete transactions run with no
        # gap note, so repairing the gap removes the notice rather than leaving
        # a permanent scar from a run that has since been superseded.
        gap_note = (
            run.notes
            if run is not None
            and run.notes is not None
            and run.notes.startswith(schwab_ingestion.HISTORY_GAP_NOTE_PREFIX)
            else None
        )

        broker_rows = await self._imported_transactions(
            user_id, account_hash, window_start, window_end
        )
        ic_trades = await self._ic_trades(
            user_id, account_id, window_start, window_end
        )

        rows = self._match(broker_rows, ic_trades)

        return TransactionReconciliationResponse(
            window_start=window_start,
            window_end=window_end,
            last_import_at=last_import_at,
            never_imported=last_import_at is None,
            newer_failed_import_at=newer_failed_import_at,
            history_gap=gap_note is not None,
            history_gap_note=gap_note,
            transaction_history_limit_days=(
                schwab_ingestion.TRANSACTION_HISTORY_LIMIT_DAYS
            ),
            matched_count=sum(1 for r in rows if r.status == "matched"),
            broker_only_count=sum(1 for r in rows if r.status == "broker_only"),
            ic_only_count=sum(1 for r in rows if r.status == "ic_only"),
            transactions=rows,
        )

    async def _imported_transactions(
        self,
        user_id: UUID,
        account_hash: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ImportedTransaction]:
        """Imported broker transactions for this user's hash in the window.

        Ordered by ``(occurred_at, id)`` - the same deterministic ordering rule
        §3 pinned for the open-lots walk, and for the same reason: broker source
        data routinely shares a timestamp across rows, and greedy matching below
        must produce the same pairing on every run.
        """
        stmt = (
            select(ImportedTransaction)
            .where(
                ImportedTransaction.user_id == user_id,
                ImportedTransaction.account_hash == account_hash,
                ImportedTransaction.occurred_at >= window_start,
                ImportedTransaction.occurred_at < window_end,
            )
            .order_by(ImportedTransaction.occurred_at, ImportedTransaction.id)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _ic_trades(
        self,
        user_id: UUID,
        account_id: int,
        window_start: datetime,
        window_end: datetime,
    ) -> list[Trade]:
        """This user's IC trades for this account in the window.

        Synthetic (adoption) trades are excluded from the match pool on
        purpose: a synthetic row is a position-level quantity plug, not a fill
        that ever happened at the broker. Matching one against a broker
        transaction would manufacture a false "matched" and hide a genuine
        broker-only fill behind it.
        """
        stmt = (
            select(Trade)
            .options(selectinload(Trade.equity))
            .where(
                Trade.user_id == user_id,
                Trade.account_id == account_id,
                Trade.executed_at >= window_start,
                Trade.executed_at < window_end,
                Trade.is_synthetic.is_(False),
            )
            .order_by(Trade.executed_at, Trade.id)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _broker_side(txn: ImportedTransaction) -> str | None:
        """Map a broker transaction's leg to an IC trade side.

        Schwab's ``transferItems[].amount`` (normalized into ``quantity``) is
        SIGNED - positive for shares coming in, negative for shares going out -
        and ``positionEffect`` says whether the leg opened or closed exposure.
        The two together are what distinguish a long buy from a short cover:

        =========  ===============  ======
        quantity   positionEffect   side
        =========  ===============  ======
        > 0        OPENING          buy
        < 0        CLOSING          sell
        < 0        OPENING          short
        > 0        CLOSING          cover
        =========  ===============  ======

        With no ``positionEffect`` (some exports omit it), the sign alone
        decides buy vs sell - the long-side reading, which is the overwhelming
        common case and the only one IC's manual entry usually holds.
        """
        qty = txn.quantity
        # is_finite() before any comparison: Postgres ``numeric`` stores NaN
        # happily, and ``Decimal("NaN") > 0`` raises InvalidOperation. Today's
        # ingestion parsers reject non-finite values, but that is a property of
        # those writers rather than of the column (see _finite), so the read
        # path guards independently - and since nothing can DELETE an
        # ImportedTransaction, a single such row would otherwise
        # 500 this view forever.
        if qty is None or not qty.is_finite() or qty == 0:
            return None
        effect = (txn.position_effect or "").upper()
        incoming = qty > 0
        if effect == "OPENING":
            return TradeType.BUY.value if incoming else TradeType.SHORT.value
        if effect == "CLOSING":
            return TradeType.COVER.value if incoming else TradeType.SELL.value
        return TradeType.BUY.value if incoming else TradeType.SELL.value

    def _match(
        self, broker_rows: list[ImportedTransaction], ic_trades: list[Trade]
    ) -> list[TransactionMatch]:
        """Pair broker transactions with IC trades; report the leftovers.

        Greedy, one-to-one, first-fit in ``(occurred_at, id)`` order: each
        broker transaction claims the earliest still-unclaimed IC trade with the
        same symbol, the same side, the same absolute quantity, and an execution
        time within :data:`_MATCH_DATE_TOLERANCE_DAYS`. One-to-one matters -
        two identical fills on the same day must consume two IC trades, so a
        user who logged only one of them still sees exactly one ``broker_only``
        row rather than both fills reading as matched.

        Deliberately NOT a price comparison: brokers report an execution price
        that can differ in the last cent from what a user typed, and a false
        mismatch here costs more than a missed one.

        LINEAR, not quadratic. The naive form ("for each broker row, scan every
        trade") is O(n*m), and a CSV upload can legitimately carry tens of
        thousands of same-symbol rows for a decade-old account - enough to hang
        a request. Two properties keep the scan bounded instead: candidates are
        bucketed by ``(symbol, side, quantity)`` so only genuinely comparable
        trades are ever walked, and within a bucket both sides are in ascending
        time order, so a per-bucket cursor can permanently retire trades that
        fall before the current row's tolerance window (no later broker row can
        reach back to them) and the scan can stop at the first trade past it.
        """
        rows: list[TransactionMatch] = []
        # Unmatched IC trades bucketed by (symbol, side, quantity); each list
        # stays in (executed_at, id) order because ic_trades already is, and a
        # claimed trade is tombstoned to None in place. Decimal hashes by
        # value, so 10 and 10.00000000 land in the same bucket.
        available: dict[tuple[str, str, Decimal], list[Trade | None]] = {}
        for trade in ic_trades:
            symbol = (trade.equity.symbol if trade.equity else "") or ""
            available.setdefault(
                (symbol.upper(), trade.trade_type.value, trade.quantity), []
            ).append(trade)

        # Per-bucket cursor: everything before it is claimed or permanently
        # out of reach. Only ever advances.
        cursors: dict[tuple[str, str, Decimal], int] = {}
        matched_trade_ids: set[int] = set()
        tolerance = timedelta(days=_MATCH_DATE_TOLERANCE_DAYS)

        for txn in broker_rows:
            side = self._broker_side(txn)
            symbol = (txn.symbol or "").upper()
            if not symbol or side is None:
                rows.append(
                    TransactionMatch(
                        status="non_trade",
                        broker_transaction_id=txn.id,
                        external_transaction_id=txn.external_transaction_id,
                        broker_source=txn.source,
                        broker_type=txn.transaction_type,
                        broker_net_amount=_finite(txn.net_amount),
                        broker_occurred_at=txn.occurred_at,
                        symbol=txn.symbol,
                        note=(
                            "No tradeable instrument leg (cash movement, "
                            "dividend, or fee) - nothing to match against a "
                            "trade."
                        ),
                    )
                )
                continue

            # _broker_side already rejected a null/zero quantity, so this is
            # always a real magnitude here.
            wanted = abs(txn.quantity) if txn.quantity is not None else None
            partner: Trade | None = None
            key = (symbol, side, wanted) if wanted is not None else None
            candidates = available.get(key) if key is not None else None
            if key is not None and candidates:
                earliest = txn.occurred_at - tolerance
                latest = txn.occurred_at + tolerance
                cursor = cursors.get(key, 0)
                # Retire the front of the bucket: already-claimed trades, and
                # trades older than THIS row's window. Broker rows ascend in
                # occurred_at, so a trade too old for this one is too old for
                # every row still to come - it can be passed permanently. (It
                # still reports as ic_only; that pass reads ic_trades, not
                # these buckets.)
                while cursor < len(candidates) and (
                    candidates[cursor] is None
                    or candidates[cursor].executed_at < earliest
                ):
                    cursor += 1
                cursors[key] = cursor

                index = cursor
                while index < len(candidates):
                    candidate = candidates[index]
                    if candidate is None:
                        index += 1
                        continue
                    if candidate.executed_at > latest:
                        # Sorted ascending, so nothing further can match either.
                        break
                    partner = candidate
                    candidates[index] = None  # claimed
                    break

            if partner is None:
                rows.append(
                    self._broker_row(txn, side, status="broker_only")
                )
            else:
                matched_trade_ids.add(partner.id)
                row = self._broker_row(txn, side, status="matched")
                row.trade_id = partner.id
                row.ic_side = partner.trade_type.value
                row.ic_quantity = _finite(partner.quantity)
                row.ic_price = _finite(partner.price)
                row.ic_executed_at = partner.executed_at
                rows.append(row)

        for trade in ic_trades:
            if trade.id in matched_trade_ids:
                continue
            rows.append(
                TransactionMatch(
                    status="ic_only",
                    trade_id=trade.id,
                    ic_side=trade.trade_type.value,
                    ic_quantity=_finite(trade.quantity),
                    ic_price=_finite(trade.price),
                    ic_executed_at=trade.executed_at,
                    symbol=(trade.equity.symbol if trade.equity else None),
                )
            )

        # Newest activity first; ties broken by symbol then status so the order
        # is total and stable across requests.
        rows.sort(
            key=lambda r: (
                -(r.broker_occurred_at or r.ic_executed_at).timestamp(),
                r.symbol or "",
                r.status,
            )
        )
        return rows

    @staticmethod
    def _broker_row(
        txn: ImportedTransaction, side: str, *, status: str
    ) -> TransactionMatch:
        return TransactionMatch(
            status=status,
            broker_transaction_id=txn.id,
            external_transaction_id=txn.external_transaction_id,
            broker_source=txn.source,
            broker_type=txn.transaction_type,
            broker_side=side,
            broker_quantity=(
                abs(txn.quantity) if txn.quantity is not None else None
            ),
            broker_price=_finite(txn.price),
            broker_net_amount=_finite(txn.net_amount),
            broker_occurred_at=txn.occurred_at,
            symbol=txn.symbol,
        )
