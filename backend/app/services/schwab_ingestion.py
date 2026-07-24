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

SESSION OWNERSHIP: :func:`pull_positions` and :func:`pull_transactions` own
their entire transactional lifecycle - each creates its OWN session from the
application sessionmaker (``AsyncSessionLocal``; injectable for tests via
``session_factory``) and never accepts a caller session. This is deliberate:
committing/rolling back a session a caller also holds would flush and commit
whatever unrelated pending state that caller had accumulated, silently
entangling an ingestion pull with work it knows nothing about. A failed pull
therefore rolls back only its own writes, and the ``status=failed`` audit
row is committed on a SECOND, fresh session (so bookkeeping survives even a
broken first connection). The read helpers (:func:`get_latest_complete_run`,
:func:`get_current_positions`) and :func:`get_connected_provider` do accept
a caller session - they never commit or roll back.

Every pull is ONE DB transaction on its own session: any API/parse/DB
failure rolls back everything written for that pull (fail closed - a partial
snapshot, or a half-applied transactions batch, must never be visible), then
the separate always-committed audit transaction records the ``status=failed``
run row (a sanitized reason only - never a raw exception's text, which could
echo request/response content) so the failure is observable without ever
leaving partial data behind.

SCHWAB HISTORY BOUNDARY: the transactions endpoint only accepts start dates
within the trailing 60 days and has no pagination past that boundary (see
``TRANSACTION_HISTORY_LIMIT_DAYS``), so the effective window start is always
clamped to that horizon. When clamping truncates the requested start - e.g.
the since-last-cursor default after a >60-day ingestion outage - the
truncation is recorded LOUDLY (``BrokerImportRun.notes`` + a warning log):
the skipped span is unrecoverable via this API, and the broker-CSV import
(sub-PR 3) is the designated recovery path.

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
from collections.abc import Callable, Iterator

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

# Schwab's transactions endpoint only accepts start dates within 60 days of
# the current date, and schwab-py implements no pagination beyond that
# boundary:
# https://schwab-py.readthedocs.io/en/stable/client.html#schwab.client.Client.get_transactions
# ("Date must be within 60 days of the current date.") A start_date older
# than this makes the WHOLE call fail - and the since-last-cursor default
# would produce exactly that after any >60-day ingestion gap - so
# pull_transactions clamps the effective window start to this horizon and
# records the truncated (API-unrecoverable) gap on the run row.
TRANSACTION_HISTORY_LIMIT_DAYS = 60
# Clamp one day inside the documented limit so a pull that computes its
# window shortly before making the call can't drift past the boundary
# mid-flight.
_TRANSACTION_START_CLAMP_DAYS = TRANSACTION_HISTORY_LIMIT_DAYS - 1

# Max width of a single get_transactions call's window. With the 60-day
# history horizon above, a clamped window always fits in one call today;
# the chunked traversal (_date_windows) is kept so a wider window would
# still be walked correctly if Schwab ever extends the horizon.
_MAX_TRANSACTION_WINDOW_DAYS = 60
_DEFAULT_TRANSACTION_LOOKBACK_DAYS = 30

_SessionFactory = Callable[[], AsyncSession]


def _default_session_factory() -> _SessionFactory:
    # Imported lazily so importing this module never eagerly builds the
    # engine (mirrors the lazy import style used elsewhere in services/).
    from app.db.session import AsyncSessionLocal

    return AsyncSessionLocal


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
    raise :class:`SchwabNotConnectedError`.

    Read-only against ``db`` at call time. NOTE: the returned provider holds
    ``db`` and will COMMIT it if schwab-py refreshes the access token during
    a later call (token persistence). The pull functions therefore hand this
    their own service-owned session, never a caller's; external callers
    doing the same should pass a session they own.
    """
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
def _decimal(value) -> Decimal | None:
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


def _primary_transfer_item(transfer_items: list | None) -> dict | None:
    """The trade-relevant leg of a transaction's ``transferItems``, if any:
    the first item carrying a ``positionEffect`` - Schwab's own signal that
    this leg is the tradeable instrument, as opposed to a CURRENCY/fee leg
    (``feeType``-only entries have no ``positionEffect``)."""
    for item in transfer_items or []:
        if isinstance(item, dict) and item.get("positionEffect"):
            return item
    return None


def _parse_schwab_datetime(value) -> datetime | None:
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
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> None:
    """Record a ``status=failed`` run row and commit ``db``.

    The pull functions call this with a FRESH service-owned session (never
    the one the failed attempt dirtied, which may hold a broken connection
    after a DB-level failure, and never a caller's), so the bookkeeping
    commit can only ever contain this one row.
    """
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
    user_id: uuid.UUID,
    account_hash: str,
    *,
    session_factory: _SessionFactory | None = None,
) -> BrokerImportRun:
    """One full positions snapshot for ``(user_id, account_hash)``.

    Owns its sessions (see the module docstring's SESSION OWNERSHIP note):
    the fetch, normalization, and every row for this run are written and
    committed on a session this function creates; any failure rolls back
    only that session and records a ``status=failed`` run on a second fresh
    session (fail closed - the previous snapshot, if any, is left untouched
    either way).

    ``session_factory`` defaults to the application ``AsyncSessionLocal``;
    tests inject a factory bound to the test engine.
    """
    factory = session_factory or _default_session_factory()
    async with factory() as db:
        provider = await get_connected_provider(db, user_id)
        try:
            try:
                # Provider API calls happen BEFORE any ingestion row is
                # added, so a mid-call token-refresh persistence commit
                # (see get_connected_provider) can never commit a partial
                # run.
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
                await db.flush()  # assign run.id without committing yet

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

                await db.commit()
                await db.refresh(run)
                return run
            except Exception as exc:
                await db.rollback()
                async with factory() as audit_db:
                    await _record_failed_run(
                        audit_db, user_id, account_hash, ImportKind.POSITIONS, exc
                    )
                raise
        finally:
            await provider.aclose()


async def get_latest_complete_run(
    db: AsyncSession, user_id: uuid.UUID, account_hash: str
) -> BrokerImportRun | None:
    """The most recent ``status=complete`` positions run for ``(user_id,
    account_hash)``, or ``None`` if positions have never been successfully
    pulled. "Current positions" = this run's ``ImportedPosition`` rows.

    Read-only; safe to call with any session.
    """
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


async def get_newer_failed_import_at(
    db: AsyncSession, user_id: uuid.UUID, account_hash: str
) -> datetime | None:
    """When the LATEST positions run is a ``failed`` one newer than the latest
    complete run (or there is no complete run at all), its ``created_at`` -
    else ``None``. Surfaces "your last pull attempt actually failed, don't
    trust that this snapshot is current" (§6 / amendment 7).

    Sibling of :func:`get_latest_complete_run`: same read-only, any-session
    contract, and scoped to ``kind=POSITIONS`` so it stays coherent with
    ``last_import_at``. A failed pull is never conflated with a complete one -
    ``ImportStatus`` already separates them; this is just a second query.
    """
    latest_any = await db.scalar(
        select(BrokerImportRun)
        .where(
            BrokerImportRun.user_id == user_id,
            BrokerImportRun.account_hash == account_hash,
            BrokerImportRun.kind == ImportKind.POSITIONS,
        )
        .order_by(BrokerImportRun.created_at.desc())
        .limit(1)
    )
    # Only the LATEST run matters: if it's complete, the latest complete run is
    # the newest thing there is, so nothing failed is newer. If it's failed, it
    # is by definition newer than any complete run (or there is none) - surface
    # it either way.
    if latest_any is None or latest_any.status != ImportStatus.FAILED:
        return None
    return latest_any.created_at


async def get_current_positions(
    db: AsyncSession, user_id: uuid.UUID, account_hash: str
) -> list[ImportedPosition]:
    """Positions from the latest complete snapshot run, or ``[]`` if none
    yet. A thin read helper for sub-PR 2 to build reconciliation on top of -
    no reconciliation logic lives here. Read-only; safe with any session."""
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

    With the 60-day history horizon (TRANSACTION_HISTORY_LIMIT_DAYS) a
    clamped window currently always fits in one chunk; this traversal is
    the safety net that keeps a wider window correct if the horizon ever
    grows.
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
    lookback for a first-ever pull. The 60-day API-horizon clamp is applied
    by pull_transactions AFTER this, so a stale cursor (long ingestion gap)
    can't produce a start date Schwab would reject."""
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


def _history_gap_note(requested_start: datetime, clamped_start: datetime) -> str:
    """The loud, run-row-visible record of an API-unrecoverable history gap."""
    return (
        f"HISTORY GAP: requested window start {requested_start.isoformat()} "
        f"predates Schwab's {TRANSACTION_HISTORY_LIMIT_DAYS}-day transaction "
        f"history boundary; start clamped to {clamped_start.isoformat()}. "
        "Transactions in the skipped span are unrecoverable via the API - "
        "the broker-CSV import (sub-PR 3) is the recovery path."
    )


async def pull_transactions(
    user_id: uuid.UUID,
    account_hash: str,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    *,
    session_factory: _SessionFactory | None = None,
) -> BrokerImportRun:
    """Pull + upsert transactions for ``(user_id, account_hash)`` in
    ``[start_date, end_date)``.

    Owns its sessions exactly like :func:`pull_positions` (see the module
    docstring's SESSION OWNERSHIP note).

    Defaults: ``start_date`` = since the last stored transaction for this
    account, or 30 days back on a first pull; ``end_date`` = now. The
    effective start is then CLAMPED to Schwab's 60-day history horizon
    (``TRANSACTION_HISTORY_LIMIT_DAYS`` - the API rejects older starts and
    has no pagination past them); a clamp that truncates the requested
    start records the unrecoverable gap on ``run.notes`` and logs a
    warning, and the run still completes with whatever the API can serve.
    Rows are normalized and upserted (by ``activityId``, so a correction
    overwrites and an overlapping re-pull never duplicates) in ONE
    transaction for the whole pull; a failure at any point rolls back all
    of it and records a failed run instead.
    """
    factory = session_factory or _default_session_factory()
    async with factory() as db:
        now = datetime.now(timezone.utc)
        window_end = end_date or now
        requested_start = start_date or await _default_transaction_window_start(
            db, user_id, account_hash
        )

        # Clamp to the API's history horizon (TRANSACTION_HISTORY_LIMIT_DAYS):
        # an unclamped stale cursor would make EVERY subsequent pull fail,
        # permanently, until someone intervened.
        clamp_floor = now - timedelta(days=_TRANSACTION_START_CLAMP_DAYS)
        window_start = max(requested_start, clamp_floor)
        notes: str | None = None
        if window_start > requested_start:
            notes = _history_gap_note(requested_start, window_start)
            logger.warning(
                "Schwab transactions pull for account_hash=%s: %s",
                account_hash,
                notes,
            )

        provider = await get_connected_provider(db, user_id)
        try:
            try:
                # All API calls happen before any ingestion row is added -
                # see pull_positions' comment on token-refresh commits.
                raw_transactions: list[dict] = []
                for chunk_start, chunk_end in _date_windows(
                    window_start, window_end, _MAX_TRANSACTION_WINDOW_DAYS
                ):
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
                    notes=notes,
                )
                db.add(run)
                await db.flush()  # assign run.id without committing yet

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

                await db.commit()
                await db.refresh(run)
                return run
            except Exception as exc:
                await db.rollback()
                async with factory() as audit_db:
                    await _record_failed_run(
                        audit_db,
                        user_id,
                        account_hash,
                        ImportKind.TRANSACTIONS,
                        exc,
                        window_start=window_start,
                        window_end=window_end,
                    )
                raise
        finally:
            await provider.aclose()
