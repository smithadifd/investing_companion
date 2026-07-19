"""Schwab positions/transactions ingestion (T2 sub-PR 1/3).

``pull -> normalize -> upsert``. Positions are whole-snapshot runs: each
successful pull creates one :class:`~app.db.models.broker_import.BrokerImportRun`
row and one :class:`~app.db.models.broker_import.ImportedPosition` row per
held symbol; "current positions" for an account = the rows FK'd to the
latest ``status=complete`` positions run (see :func:`get_current_positions`).
A re-pull is a new run (history), never an in-place update of a prior run's
rows.

Transactions are upserted by Schwab's stable ``activityId``: a re-pull over
an overlapping window updates existing rows in place (a Schwab correction,
same ID with changed fields, overwrites) and never duplicates. Deletions are
out of scope for v1.

Every pull is ONE DB transaction: any API/parse/DB failure rolls back
everything written so far for that pull (fail closed - a partial snapshot,
or a half-applied transactions batch, must never be visible), then a
SEPARATE always-committed transaction records a ``status=failed`` run row
(a sanitized reason only - never a raw exception's text, which could echo
request/response content) so the failure is observable without ever leaving
partial data behind.

NO reconciliation logic and NO API endpoint/UI here - those are sub-PR 2 and
the existing Settings UI respectively. This module only lands the ingestion
primitive: given a user + an already-known Schwab account hash, pull once,
normalize, and write.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterator, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.broker_import import (
    BrokerImportRun,
    ImportedPosition,
    ImportedTransaction,
    ImportKind,
    ImportStatus,
)
from app.services.data_providers.schwab import (
    SchwabAPIError,
    SchwabAuthError,
    SchwabProvider,
    is_schwab_configured,
    parse_wrapped_token,
    token_is_expired,
)

logger = logging.getLogger(__name__)

SOURCE = "schwab_api"

# Schwab's transactions endpoint caps a single call's window at 60 days
# (schwab-py's own default lookback when start_date is omitted). A wide
# cursor gap (a first-ever pull, or one resuming after a long outage) is
# walked in <=60-day chunks - see _date_windows.
_MAX_TRANSACTION_WINDOW_DAYS = 60
_DEFAULT_TRANSACTION_LOOKBACK_DAYS = 30


class SchwabNotConnectedError(Exception):
    """No usable Schwab token for this user: never configured, no token
    stored, an unparseable token, or one past the 7-day hard expiry.

    Distinct from ``SchwabAuthError`` (a live API call was rejected) - this
    is raised before any API call is attempted, so callers/operators can
    tell "needs (re)connecting" apart from "was connected, Schwab said no".
    """


# ---------------------------------------------------------------------------
# Provider construction - deliberately NOT the same as
# get_extended_quote_provider, which silently falls back to Yahoo. Imported
# holdings/transactions have no safe substitute for a real connection, so a
# missing/expired token is an explicit, typed failure (an Andrew re-auth
# gate), never silent.
# ---------------------------------------------------------------------------
async def get_connected_provider(
    db: AsyncSession, user_id: uuid.UUID
) -> SchwabProvider:
    """Build a ``SchwabProvider`` bound to ``user_id``'s stored token, or
    raise :class:`SchwabNotConnectedError`."""
    if not is_schwab_configured():
        raise SchwabNotConnectedError("Schwab is not configured on this server")

    from app.services.settings import SettingsService

    service = SettingsService(db)
    raw_token = await service.get_setting(SettingsService.SCHWAB_TOKEN, user_id)
    wrapped = parse_wrapped_token(raw_token)
    if wrapped is None:
        raise SchwabNotConnectedError("No Schwab token connected for this user")
    if token_is_expired(wrapped):
        raise SchwabNotConnectedError(
            "Schwab token has passed its 7-day expiry; reconnect required"
        )
    return SchwabProvider(db, user_id, wrapped, fallback=None)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def _decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _normalize_position(raw: dict) -> dict:
    """Map one raw (already account-number-redacted) Schwab position dict to
    ``ImportedPosition`` column kwargs.

    Signed ``quantity`` = longQuantity - shortQuantity, so a short position
    carries a negative net quantity (binding design point 4).
    """
    instrument = raw.get("instrument") or {}
    symbol = instrument.get("symbol")
    if not symbol:
        raise SchwabAPIError("Schwab position missing instrument.symbol")

    long_qty = _decimal(raw.get("longQuantity")) or Decimal("0")
    short_qty = _decimal(raw.get("shortQuantity")) or Decimal("0")

    return {
        "symbol": symbol,
        "asset_type": instrument.get("assetType") or "UNKNOWN",
        "cusip": instrument.get("cusip"),
        "quantity": long_qty - short_qty,
        "long_quantity": long_qty,
        "short_quantity": short_qty,
        "average_price": _decimal(raw.get("averagePrice")),
        "market_value": _decimal(raw.get("marketValue")),
        "current_day_profit_loss": _decimal(raw.get("currentDayProfitLoss")),
        "raw": raw,
    }


def _primary_transfer_item(transfer_items: Optional[list]) -> Optional[dict]:
    """The trade-relevant leg of a transaction's ``transferItems``, if any:
    the first item carrying a ``positionEffect`` - Schwab's own signal that
    this leg is the tradeable instrument, as opposed to a CURRENCY/fee leg
    (``feeType``-only entries have no ``positionEffect``)."""
    for item in transfer_items or []:
        if isinstance(item, dict) and item.get("positionEffect"):
            return item
    return None


def _parse_schwab_datetime(value) -> Optional[datetime]:
    """Parse Schwab's ``YYYY-MM-DDTHH:MM:SS+0000``-style timestamps to an
    aware UTC ``datetime``."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    # datetime.fromisoformat wants a colon in the UTC offset; Schwab's
    # format omits it ("+0000" not "+00:00").
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = f"{text[:-2]}:{text[-2:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_transaction(raw: dict) -> dict:
    """Map one raw (already account-number-redacted) Schwab transaction dict
    to ``ImportedTransaction`` column kwargs."""
    external_id = raw.get("activityId")
    if external_id is None:
        raise SchwabAPIError("Schwab transaction missing activityId")

    occurred_at = _parse_schwab_datetime(raw.get("tradeDate") or raw.get("time"))
    if occurred_at is None:
        raise SchwabAPIError("Schwab transaction missing a usable date")

    primary = _primary_transfer_item(raw.get("transferItems")) or {}
    instrument = primary.get("instrument") or {}
    order_id = raw.get("orderId")

    return {
        "external_transaction_id": str(external_id),
        "transaction_type": raw.get("type") or "UNKNOWN",
        "status": raw.get("status"),
        "sub_account": raw.get("subAccount"),
        "symbol": instrument.get("symbol"),
        "asset_type": instrument.get("assetType"),
        "quantity": _decimal(primary.get("amount")),
        "price": _decimal(primary.get("price")),
        "net_amount": _decimal(raw.get("netAmount")),
        "position_effect": primary.get("positionEffect"),
        "order_id": str(order_id) if order_id is not None else None,
        "occurred_at": occurred_at,
        "raw": raw,
    }


# ---------------------------------------------------------------------------
# Failure bookkeeping
# ---------------------------------------------------------------------------
def _safe_error_reason(exc: Exception) -> str:
    """A DB-safe, PII-safe description of ``exc``.

    Our own exceptions (``SchwabAuthError``/``SchwabAPIError``/
    ``SchwabNotConnectedError``) carry messages we wrote ourselves, built
    only from fixed strings, HTTP status codes, and exception *type* names
    (never response bodies) - see ``schwab.py``. Those are safe to store
    verbatim. Any other exception (a DB error, an unexpected library
    internal, ...) is from code this module doesn't fully control, so only
    its type name is kept - never its message, which could in principle
    echo request/response content.
    """
    if isinstance(exc, (SchwabAuthError, SchwabAPIError, SchwabNotConnectedError)):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__


async def _record_failed_run(
    db: AsyncSession,
    user_id: uuid.UUID,
    account_hash: str,
    kind: ImportKind,
    exc: Exception,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> None:
    """Record a ``status=failed`` run row in its own (always-committed)
    transaction, so a failed pull is observable without ever attaching
    partial position/transaction rows. Called from inside the ``except``
    that wraps the failed attempt's ``db.begin_nested()`` block, which has
    already rolled back to the savepoint by the time this runs."""
    reason = _safe_error_reason(exc)
    run = BrokerImportRun(
        user_id=user_id,
        account_hash=account_hash,
        source=SOURCE,
        kind=kind,
        status=ImportStatus.FAILED,
        window_start=window_start,
        window_end=window_end,
        error_message=reason,
    )
    db.add(run)
    await db.commit()
    logger.warning(
        "Schwab %s pull failed for account_hash=%s: %s",
        kind.value,
        account_hash,
        reason,
    )


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------
async def pull_positions(
    db: AsyncSession, user_id: uuid.UUID, account_hash: str
) -> BrokerImportRun:
    """One full positions snapshot for ``(user_id, account_hash)``.

    Fetches, normalizes, and inserts every current position inside a single
    DB transaction alongside the run row; any failure rolls all of it back
    and records a separate failed-run row instead (fail closed - the
    previous snapshot, if any, is left untouched either way).
    """
    provider = await get_connected_provider(db, user_id)
    try:
        try:
            # The fetch, normalize, and every write for this run share one
            # SAVEPOINT: an exception anywhere inside - the API call, a
            # malformed row, or a DB-level failure on flush - rolls back
            # everything written so far for THIS attempt and nothing else
            # (the previous snapshot, if any, was never touched to begin
            # with). Using a SAVEPOINT block here rather than a bare
            # ``await db.rollback()`` keeps this safe to call on a session
            # that may have other pending work outside this function's
            # control.
            async with db.begin_nested():
                raw_positions = await provider.get_positions(account_hash)
                normalized = [_normalize_position(p) for p in raw_positions]

                run = BrokerImportRun(
                    user_id=user_id,
                    account_hash=account_hash,
                    source=SOURCE,
                    kind=ImportKind.POSITIONS,
                    status=ImportStatus.COMPLETE,
                    item_count=len(normalized),
                )
                db.add(run)
                await db.flush()  # assign run.id within the savepoint

                for kwargs in normalized:
                    db.add(
                        ImportedPosition(
                            import_run_id=run.id,
                            user_id=user_id,
                            account_hash=account_hash,
                            source=SOURCE,
                            **kwargs,
                        )
                    )
        except Exception as exc:
            await _record_failed_run(
                db, user_id, account_hash, ImportKind.POSITIONS, exc
            )
            raise

        await db.commit()
        await db.refresh(run)
        return run
    finally:
        await provider.aclose()


async def get_latest_complete_run(
    db: AsyncSession, user_id: uuid.UUID, account_hash: str
) -> Optional[BrokerImportRun]:
    """The most recent ``status=complete`` positions run for ``(user_id,
    account_hash)``, or ``None`` if positions have never been successfully
    pulled. "Current positions" = this run's ``ImportedPosition`` rows."""
    stmt = (
        select(BrokerImportRun)
        .where(
            BrokerImportRun.user_id == user_id,
            BrokerImportRun.account_hash == account_hash,
            BrokerImportRun.kind == ImportKind.POSITIONS,
            BrokerImportRun.status == ImportStatus.COMPLETE,
        )
        .order_by(BrokerImportRun.created_at.desc())
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_current_positions(
    db: AsyncSession, user_id: uuid.UUID, account_hash: str
) -> list[ImportedPosition]:
    """Positions from the latest complete snapshot run, or ``[]`` if none
    yet. A thin read helper for sub-PR 2 to build reconciliation on top of -
    no reconciliation logic lives here."""
    run = await get_latest_complete_run(db, user_id, account_hash)
    if run is None:
        return []
    stmt = select(ImportedPosition).where(ImportedPosition.import_run_id == run.id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------
def _date_windows(
    start: datetime, end: datetime, max_days: int = _MAX_TRANSACTION_WINDOW_DAYS
) -> Iterator[tuple[datetime, datetime]]:
    """Yield consecutive ``[chunk_start, chunk_end)`` windows no wider than
    ``max_days``, covering ``[start, end)``.

    Schwab's transactions endpoint has no cursor/next-page token - its only
    pagination primitive is this date-window cap - so a wide requested range
    is walked as repeated calls, one per chunk (this is what the binding
    design's "full pagination traversal" means here).
    """
    if end <= start:
        return
    step = timedelta(days=max_days)
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + step, end)
        yield cursor, chunk_end
        cursor = chunk_end


async def _default_transaction_window_start(
    db: AsyncSession, user_id: uuid.UUID, account_hash: str
) -> datetime:
    """Start of the pull window when the caller doesn't pass one explicitly:
    the latest already-imported transaction's time for this account (so a
    routine re-pull only asks for what's new), else a 30-day default
    lookback for a first-ever pull."""
    latest = await db.scalar(
        select(func.max(ImportedTransaction.occurred_at)).where(
            ImportedTransaction.user_id == user_id,
            ImportedTransaction.account_hash == account_hash,
        )
    )
    if latest is not None:
        return latest
    return datetime.now(timezone.utc) - timedelta(
        days=_DEFAULT_TRANSACTION_LOOKBACK_DAYS
    )


async def pull_transactions(
    db: AsyncSession,
    user_id: uuid.UUID,
    account_hash: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> BrokerImportRun:
    """Pull + upsert transactions for ``(user_id, account_hash)`` in
    ``[start_date, end_date)``.

    Defaults: ``start_date`` = since the last stored transaction for this
    account, or 30 days back on a first pull; ``end_date`` = now. A wide
    window is walked in <=60-day chunks (see ``_date_windows``). Every
    chunk's rows are normalized and upserted (by ``activityId``, so a
    correction overwrites and an overlapping re-pull never duplicates)
    inside ONE DB transaction for the whole pull; a failure at any point
    rolls back all of it and records a failed run instead.
    """
    window_end = end_date or datetime.now(timezone.utc)
    window_start = start_date or await _default_transaction_window_start(
        db, user_id, account_hash
    )

    provider = await get_connected_provider(db, user_id)
    try:
        try:
            # See pull_positions' comment: the whole fetch (every chunk),
            # normalize, and upsert phase shares one SAVEPOINT, so a
            # failure at any chunk rolls back every row written for this
            # attempt, never a partially-applied pull.
            async with db.begin_nested():
                raw_transactions: list[dict] = []
                for chunk_start, chunk_end in _date_windows(window_start, window_end):
                    chunk = await provider.get_transactions(
                        account_hash, chunk_start, chunk_end
                    )
                    raw_transactions.extend(chunk)

                normalized = [_normalize_transaction(t) for t in raw_transactions]

                run = BrokerImportRun(
                    user_id=user_id,
                    account_hash=account_hash,
                    source=SOURCE,
                    kind=ImportKind.TRANSACTIONS,
                    status=ImportStatus.COMPLETE,
                    window_start=window_start,
                    window_end=window_end,
                    item_count=len(normalized),
                )
                db.add(run)
                await db.flush()  # assign run.id within the savepoint

                for kwargs in normalized:
                    stmt = pg_insert(ImportedTransaction).values(
                        import_run_id=run.id,
                        user_id=user_id,
                        account_hash=account_hash,
                        source=SOURCE,
                        **kwargs,
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["user_id", "external_transaction_id"],
                        set_={
                            "import_run_id": stmt.excluded.import_run_id,
                            "account_hash": stmt.excluded.account_hash,
                            "transaction_type": stmt.excluded.transaction_type,
                            "status": stmt.excluded.status,
                            "sub_account": stmt.excluded.sub_account,
                            "symbol": stmt.excluded.symbol,
                            "asset_type": stmt.excluded.asset_type,
                            "quantity": stmt.excluded.quantity,
                            "price": stmt.excluded.price,
                            "net_amount": stmt.excluded.net_amount,
                            "position_effect": stmt.excluded.position_effect,
                            "order_id": stmt.excluded.order_id,
                            "occurred_at": stmt.excluded.occurred_at,
                            "raw": stmt.excluded.raw,
                            # Core-level upsert bypasses the ORM
                            # unit-of-work, so TimestampMixin's
                            # onupdate=func.now() never fires here.
                            "updated_at": func.now(),
                        },
                    )
                    await db.execute(stmt)
        except Exception as exc:
            await _record_failed_run(
                db,
                user_id,
                account_hash,
                ImportKind.TRANSACTIONS,
                exc,
                window_start=window_start,
                window_end=window_end,
            )
            raise

        await db.commit()
        await db.refresh(run)
        return run
    finally:
        await provider.aclose()
