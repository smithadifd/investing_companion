"""Generic broker-CSV import (T2 sub-PR 3) - the history recovery path.

WHY THIS EXISTS - the 60-day horizon
------------------------------------
Schwab's transactions endpoint only accepts start dates within the trailing
:data:`~app.services.schwab_ingestion.TRANSACTION_HISTORY_LIMIT_DAYS` (60) days
and offers no pagination past that boundary, so
:func:`~app.services.schwab_ingestion.pull_transactions` CLAMPS its effective
window start to that horizon. When the clamp truncates a requested start - the
since-last-cursor default after any ingestion gap longer than the horizon, or
simply a first-ever import of an account with years of history - the skipped
span is **unrecoverable via the API, permanently**. The pull records that
loudly (``BrokerImportRun.notes``, prefixed
:data:`~app.services.schwab_ingestion.HISTORY_GAP_NOTE_PREFIX`) and the
transactions reconciliation envelope surfaces it. This module is what repairs
it: a broker CSV export reaches back as far as the broker's own web export
does, which is years rather than 60 days.

That is the whole design rationale, and it is why this writes into the SAME
:class:`~app.db.models.broker_import.ImportedTransaction` table the API pull
writes into, distinguished only by ``source="csv_import"``. The broker_import
tables were declared broker-agnostic for exactly this
("generic 'imported' tables so a future broker-CSV import (sub-PR 3) can reuse
the same shape with a different ``source`` value"), so CSV-recovered rows
reconcile side by side with API-pulled rows in one view rather than living in
a parallel universe.

FORMAT - deliberately generic
-----------------------------
Column headers are matched against synonym sets rather than a fixed schema, so
a Schwab "Transactions" export works out of the box and any broker CSV with
recognizable date / action / symbol / quantity / price columns works too.
Preamble lines above the header (Schwab writes one) are skipped by scanning
for the first row that looks like a header. Rows the parser understands but
will not import are reported individually with a reason - never silently
dropped, the same rule §5 applies to ineligible positions.

IDEMPOTENCY
-----------
``ImportedTransaction`` is upserted on ``(user_id, external_transaction_id)``,
so the key a row derives decides whether a second upload updates it or adds
beside it. One key is built per row, in two steps.

*Base*: the broker's own reference number when the file has an id column,
otherwise a sha256 of the row's normalized content. Either way it is prefixed
``csv:`` so it can never collide with Schwab's numeric ``activityId`` in the
shared column, and namespaced by the broker account - the constraint does NOT
include ``account_hash``, while one user may legitimately link several broker
accounts and a reference number is only unique within the account that issued
it (see the comment at the derivation site).

*Occurrence suffix*: ``:n`` for the nth row in this upload sharing that base.
This applies to BOTH schemes, deliberately. A reference number is *supposed*
to be unique but nothing enforces it, and content is not unique at all, so
without the suffix a second row sharing a base would overwrite the first -
losing a real fill while ``skipped`` stays empty and ``imported_count`` still
counts it. That failure is worse than a duplicate: the user is told the
history was recovered, and the fill that should have surfaced as
``broker_only`` - the entire product promise of the activity view - silently
no longer exists.

Re-uploading the same export therefore updates in place rather than
duplicating (the same rows re-derive the same bases in the same order, so the
same occurrences), while two genuinely distinct rows never merge.

Known limitation, stated rather than hidden: occurrences are counted WITHIN
one upload, not against already-persisted rows. So a THIRD row sharing a base
that arrives in a LATER upload re-derives ``:1`` and updates the first row
instead of adding a third. For the derived (content-hash) scheme every field
it writes is identical by construction, so nothing is corrupted - only the
count of that repeated fill is under-reported. Closing it would mean reading
persisted state mid-parse, trading this module's atomicity and re-upload
idempotency for a rarer counting case; that is a bad trade, so the behavior is
documented instead.

SESSION OWNERSHIP - and why it differs from the pulls
-----------------------------------------------------
``schwab_ingestion``'s pull functions refuse a caller's session because the
``SchwabProvider`` they hold will COMMIT that session if schwab-py refreshes
the access token mid-call - committing a caller's session would flush whatever
unrelated pending state the caller had accumulated. This module has no
provider, makes no network call, and can never trigger a token-refresh commit,
so that hazard does not exist here. It therefore uses the caller's
request-scoped session, exactly like every other mutating service in this
codebase (``AccountLinkService.link_account``, ``TradeService.create_trade``),
and commits ONCE.

ATOMICITY: parsing happens entirely in memory first; the database is not
touched until every row has been classified. The run row and all of its
transaction rows are then written and committed in ONE transaction, so a
half-applied file is never observable. A file with no usable header is
rejected before any write at all (the caller maps it to 422), which is why -
unlike a pull - there is no ``status=failed`` audit row to write: the failure
is returned synchronously to the human who uploaded it, not discovered later.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.broker_import import (
    BrokerImportRun,
    ImportedTransaction,
    ImportKind,
    ImportStatus,
)
from app.schemas.broker_import import CsvImportResponse, CsvSkippedRow
from app.services.account_link import AccountLinkService
from app.services.schwab_ingestion import TRANSACTION_HISTORY_LIMIT_DAYS

logger = logging.getLogger(__name__)

SOURCE = "csv_import"

# Guardrails on a user-supplied file. Both are generous for a real broker
# export (a decade of a busy account is well under 25k rows) and exist only so
# a pathological upload can't exhaust memory.
MAX_CSV_BYTES = 5_000_000
MAX_CSV_ROWS = 25_000

# Column bounds. quantity/price are Numeric(18, 8) -> 10 integer digits;
# net_amount is Numeric(16, 2) -> 14. A value at or past these would be
# rejected by Postgres as a 500 rather than reported as a bad row.
_MAX_NUMERIC_18_8 = Decimal(10) ** 10
_MAX_NUMERIC_16_2 = Decimal(10) ** 14

# Header synonyms, lowercased and stripped of punctuation/whitespace by
# _norm_header. Order within a set does not matter; the FIRST matching column
# in the file wins for each field.
_HEADERS: dict[str, set[str]] = {
    "date": {
        "date",
        "tradedate",
        "transactiondate",
        "activitydate",
        "rundate",
        "executiondate",
        "occurredat",
    },
    "action": {
        "action",
        "type",
        "transactiontype",
        "side",
        "buysell",
        "buysellindicator",
        "activity",
        "activitytype",
    },
    "symbol": {"symbol", "ticker", "security", "securitysymbol", "instrument"},
    "quantity": {"quantity", "qty", "shares", "numberofshares", "sharequantity"},
    "price": {"price", "priceusd", "executionprice", "shareprice", "unitprice"},
    "fees": {"feescomm", "fees", "commission", "commissionfees", "feesandcomm"},
    "amount": {"amount", "netamount", "netcash", "total", "proceeds", "value"},
    "external_id": {
        "transactionid",
        "activityid",
        "referencenumber",
        "reference",
        "id",
        "confirmationnumber",
    },
}

# Action text -> (IC-comparable side, signed-quantity multiplier,
# positionEffect). The positionEffect is stored so
# ``ReconciliationService._broker_side`` reconstructs the SAME side from a
# CSV row that it does from an API row - one matching rule, two lanes.
# Longest patterns are checked first so "buy to cover" never matches "buy".
_ACTIONS: list[tuple[str, str, int, str]] = [
    ("buy to cover", "cover", 1, "CLOSING"),
    ("buytocover", "cover", 1, "CLOSING"),
    ("cover", "cover", 1, "CLOSING"),
    ("sell short", "short", -1, "OPENING"),
    ("sellshort", "short", -1, "OPENING"),
    ("short sale", "short", -1, "OPENING"),
    ("reinvest shares", "buy", 1, "OPENING"),
    ("buy", "buy", 1, "OPENING"),
    ("bought", "buy", 1, "OPENING"),
    ("purchase", "buy", 1, "OPENING"),
    ("sell", "sell", -1, "CLOSING"),
    ("sold", "sell", -1, "CLOSING"),
]

# Minimum columns that make a header row a header row. All three are required
# because all three are needed to classify a single fill: WHEN it happened,
# WHAT it was, and WHICH instrument. Accepting a file missing the action
# column (the old "symbol OR action" rule) meant every trade in it silently
# imported as a cash movement, which reads to the user as "nothing to
# reconcile" - the exact silently-wrong outcome this module exists to avoid.
_REQUIRED_HEADERS = ("date", "action", "symbol")

# How far into a file to look for the header. Broker exports put a title line
# or two above it; a "header" found 50 rows in is far more likely to be data
# that happens to look like one.
_MAX_HEADER_SCAN_ROWS = 10


def _missing_header_detail(scanned: list[list[str]]) -> str:
    """A 422 message naming which required columns were never found."""
    best: set[str] = set()
    for row in scanned:
        found = {
            field
            for index, raw in enumerate(row)
            for field, synonyms in _HEADERS.items()
            if _norm_header(raw or "") in synonyms
        }
        if len(found & set(_REQUIRED_HEADERS)) > len(best & set(_REQUIRED_HEADERS)):
            best = found
    missing = [f for f in _REQUIRED_HEADERS if f not in best]
    return (
        "Could not find a transaction header row. A transaction export needs "
        f"{', '.join(_REQUIRED_HEADERS)} columns"
        + (f" (missing: {', '.join(missing)})" if best else "")
        + " - e.g. Schwab's Date / Action / Symbol / Quantity / Price export."
    )


class CsvFormatError(Exception):
    """The upload isn't a recognizable transaction CSV (caller -> 422)."""


class NoActiveLinkError(Exception):
    """The account has no active broker link to attribute the rows to."""


def _norm_header(value: str) -> str:
    """Lowercase and strip everything that isn't a letter or digit.

    Turns ``"Fees & Comm"``, ``"fees_and_comm"`` and ``"FEES & COMM."`` all
    into ``feesandcomm``, so the synonym sets stay short and readable.
    """
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _map_columns(header: list[str]) -> dict[str, int] | None:
    """Map field name -> column index, or ``None`` if this isn't a header."""
    mapping: dict[str, int] = {}
    for index, raw in enumerate(header):
        norm = _norm_header(raw or "")
        if not norm:
            continue
        for field, synonyms in _HEADERS.items():
            if field in mapping:
                continue  # first matching column wins
            if norm in synonyms:
                mapping[field] = index
                break
    if any(field not in mapping for field in _REQUIRED_HEADERS):
        return None
    return mapping


def _cell(row: list[str], mapping: dict[str, int], field: str) -> str:
    index = mapping.get(field)
    if index is None or index >= len(row):
        return ""
    return (row[index] or "").strip()


def _decimal(value: str) -> Decimal | None:
    """Parse a broker-formatted number: ``$1,234.56``, ``(12.00)``, ``-5``.

    REJECTS NON-FINITE VALUES. ``Decimal("NaN")``, ``Decimal("Infinity")`` and
    ``Decimal("sNaN")`` are all perfectly valid Python constructions, so a
    literal ``NaN`` in a Quantity or Price cell would otherwise sail through
    this parser AND through Postgres (``numeric`` accepts NaN) and only
    detonate later, on every subsequent READ of the reconciliation view -
    ``NaN > 0`` raises ``InvalidOperation``, and a NaN price fails pydantic
    when the response model is built. Since nothing in this application can
    delete an ``ImportedTransaction`` ("deletions are out of scope for v1"),
    that would brick the account's activity view until someone hand-edited the
    database. Validation belongs on the WRITE side, here, where the only cost
    of rejection is one reported skipped row.
    """
    text = value.strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace("$", "").replace(" ", "").strip()
    # Decimal separator: when a number carries both '.' and ',', the LAST of
    # the two is the decimal point and the other is a grouping separator -
    # which reads "1,234.56" and "1.234,56" both correctly. A comma-only
    # number stays US-style grouping ("1,234" -> 1234); that case is genuinely
    # ambiguous and US grouping is what broker exports produce in practice.
    if "," in text and "." in text:
        if text.rindex(",") > text.rindex("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", "")
    if not text or text in {"-", "--", "N/A", "n/a"}:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():  # NaN / sNaN / +-Infinity
        return None
    return -parsed if negative else parsed


_DATE_FORMATS = (
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m-%d-%Y",
    "%b %d, %Y",
    "%d %b %Y",
    # Date + time variants: a plain "08/11/2026 12:00:00" is a common export
    # shape and was previously rejected row by row.
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
)


def _parse_date(value: str) -> datetime | None:
    """Parse a broker date cell to an aware UTC datetime.

    Handles Schwab's ``"08/11/2026 as of 08/10/2026"`` by taking the FIRST
    date (the trade date, not the settlement/as-of date). A date-only cell
    becomes UTC midnight; the transactions matcher's whole-day tolerance is
    what absorbs the resulting timezone imprecision, which is exactly why that
    tolerance is measured in days rather than minutes.
    """
    text = value.strip()
    if not text:
        return None
    if " as of " in text.lower():
        text = text[: text.lower().index(" as of ")].strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _classify_action(action: str) -> tuple[str, int, str] | None:
    """(side, sign, positionEffect) for a trade action, else ``None``.

    Matched on WORD boundaries, not bare substrings: an action or description
    cell can carry a security name, and "SELLAS LIFE SCIENCES" must not read
    as a sell.
    """
    text = action.lower().strip()
    if not text:
        return None
    for pattern, side, sign, effect in _ACTIONS:
        if re.search(rf"\b{re.escape(pattern)}\b", text):
            return side, sign, effect
    return None


class BrokerCsvImportService:
    """Parses a broker CSV and lands it as imported transactions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.links = AccountLinkService(db)

    async def import_csv(
        self,
        user_id: UUID,
        account_id: int,
        content: str,
        *,
        filename: str | None = None,
        link_source: str = "schwab_api",
    ) -> CsvImportResponse:
        """Import ``content`` as this account's broker transactions.

        The caller is expected to have already 404'd an account that isn't the
        user's. Raises :class:`NoActiveLinkError` (caller -> 409) or
        :class:`CsvFormatError` (caller -> 422).

        Cross-user isolation: ``user_id`` is the AUTHENTICATED user. It scopes
        the link lookup, is stamped on the run row and on every transaction
        row, and is half of the upsert conflict target - so one user's upload
        can neither read nor overwrite another user's transaction, even when
        both users' rows would derive the identical content hash from the
        identical file.
        """
        link = await self.links.get_active_link(user_id, account_id, link_source)
        if link is None:
            raise NoActiveLinkError()
        account_hash = link.account_hash

        if len(content.encode("utf-8")) > MAX_CSV_BYTES:
            raise CsvFormatError(
                f"CSV is larger than the {MAX_CSV_BYTES // 1_000_000}MB limit."
            )

        parsed, skipped = self._parse(content, account_hash)

        # --- Everything above is pure/in-memory. The single write follows. ---
        run = BrokerImportRun(
            user_id=user_id,
            account_hash=account_hash,
            source=SOURCE,
            kind=ImportKind.TRANSACTIONS,
            status=ImportStatus.COMPLETE,
            window_start=min((p["occurred_at"] for p in parsed), default=None),
            window_end=max((p["occurred_at"] for p in parsed), default=None),
            item_count=len(parsed),
            notes=self._run_note(filename, len(parsed), len(skipped)),
        )
        self.db.add(run)
        await self.db.flush()  # assign run.id without committing yet

        for kwargs in parsed:
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
                    "source": stmt.excluded.source,
                    "transaction_type": stmt.excluded.transaction_type,
                    "symbol": stmt.excluded.symbol,
                    "asset_type": stmt.excluded.asset_type,
                    "quantity": stmt.excluded.quantity,
                    "price": stmt.excluded.price,
                    "net_amount": stmt.excluded.net_amount,
                    "position_effect": stmt.excluded.position_effect,
                    "occurred_at": stmt.excluded.occurred_at,
                    "raw": stmt.excluded.raw,
                    # Core-level upsert bypasses the ORM unit of work, so
                    # TimestampMixin's onupdate never fires - same reason
                    # schwab_ingestion sets it explicitly.
                    "updated_at": func.now(),
                },
            )
            await self.db.execute(stmt)

        await self.db.commit()
        await self.db.refresh(run)

        logger.info(
            "Broker CSV import for account_id=%s: %d imported, %d skipped",
            account_id,
            len(parsed),
            len(skipped),
        )
        return CsvImportResponse(
            account_id=account_id,
            run=run,
            imported_count=len(parsed),
            skipped=skipped,
            earliest_occurred_at=run.window_start,
            latest_occurred_at=run.window_end,
        )

    @staticmethod
    def _run_note(filename: str | None, imported: int, skipped: int) -> str:
        """A provenance note on the run row.

        Deliberately does NOT start with ``HISTORY GAP:`` - a CSV run repairs
        the gap, so the transactions envelope must read this run as gap-free
        and drop the recovery banner.
        """
        name = f" from {filename}" if filename else ""
        return (
            f"CSV import{name}: {imported} transaction(s) imported, "
            f"{skipped} row(s) skipped. Recovery path for activity older than "
            f"Schwab's {TRANSACTION_HISTORY_LIMIT_DAYS}-day API history horizon."
        )

    def _parse(
        self, content: str, account_hash: str
    ) -> tuple[list[dict], list[CsvSkippedRow]]:
        """Parse CSV text into ``ImportedTransaction`` kwargs + skip reports."""
        # utf-8-sig handling: a BOM would otherwise poison the first header.
        text = content.lstrip("﻿")
        reader = csv.reader(io.StringIO(text))

        # Header scan reads only the first few rows; the rest is consumed
        # incrementally so the row cap is enforced BEFORE the whole file is
        # materialized, not after.
        preamble: list[list[str]] = []
        mapping: dict[str, int] | None = None
        for row in reader:
            preamble.append(row)
            mapping = _map_columns(row)
            if mapping is not None:
                break
            if len(preamble) >= _MAX_HEADER_SCAN_ROWS:
                break
        if not preamble:
            raise CsvFormatError("The uploaded file is empty.")
        if mapping is None:
            raise CsvFormatError(_missing_header_detail(preamble))

        parsed: list[dict] = []
        skipped: list[CsvSkippedRow] = []
        # Counts identical row identities so genuine repeated fills stay
        # distinct rows while a re-upload of the same file is idempotent.
        seen: Counter[str] = Counter()
        # How many rows looked like real trades (symbol + quantity) but had no
        # classifiable action. Used to tell "this file has no trades in it"
        # apart from "this file's action column was never understood".
        unclassified_trade_rows = 0
        offset = 0

        for row in reader:
            if not any((cell or "").strip() for cell in row):
                continue  # blank separator line - not worth reporting
            offset += 1
            if offset > MAX_CSV_ROWS:
                raise CsvFormatError(f"CSV has more than {MAX_CSV_ROWS} data rows.")
            record, reason = self._parse_row(
                row, mapping, account_hash, offset, seen
            )
            if record is None:
                skipped.append(reason)
                if reason.reason == "unrecognized_action":
                    unclassified_trade_rows += 1
            else:
                parsed.append(record)

        # Structural failure, not a per-row one: every trade-shaped row in the
        # file was unclassifiable, which means the action VOCABULARY wasn't
        # understood (an "Buy/Sell"-style column whose values this parser
        # doesn't know) rather than that the account genuinely had no trades.
        # Importing those as cash movements would describe real buys to the
        # user as transfers and report "nothing to reconcile" - silently wrong,
        # which is strictly worse than refusing the file.
        if unclassified_trade_rows and not any(
            p["quantity"] is not None for p in parsed
        ):
            raise CsvFormatError(
                f"Found {unclassified_trade_rows} trade row(s) but could not "
                "recognize any of their actions (e.g. Buy / Sell / Sell Short / "
                "Buy to Cover). Check that the action column exported values, "
                "not codes."
            )

        return parsed, skipped

    def _parse_row(
        self,
        row: list[str],
        mapping: dict[str, int],
        account_hash: str,
        row_number: int,
        seen: Counter[str],
    ) -> tuple[dict | None, CsvSkippedRow | None]:
        occurred_at = _parse_date(_cell(row, mapping, "date"))
        if occurred_at is None:
            return None, CsvSkippedRow(
                row_number=row_number,
                reason="unparseable_date",
                detail=(
                    f"Could not read a date from {_cell(row, mapping, 'date')!r}."
                ),
            )

        action = _cell(row, mapping, "action")
        symbol = _cell(row, mapping, "symbol").upper() or None
        classified = _classify_action(action)
        raw_quantity = _decimal(_cell(row, mapping, "quantity"))
        price = _decimal(_cell(row, mapping, "price"))
        net_amount = _decimal(_cell(row, mapping, "amount"))

        quantity: Decimal | None = None
        position_effect: str | None = None
        if classified is not None and symbol and raw_quantity is not None:
            _side, sign, position_effect = classified
            # Store the SIGNED quantity Schwab's API lane stores, so both lanes
            # reconstruct the same side through the same rule.
            quantity = abs(raw_quantity) * sign
        elif classified is not None and symbol and raw_quantity is None:
            return None, CsvSkippedRow(
                row_number=row_number,
                reason="missing_quantity",
                detail=(
                    f"{action or 'Trade'} row for {symbol} has no readable "
                    "quantity."
                ),
            )
        elif classified is None and symbol and raw_quantity is not None:
            # TRADE-SHAPED but unclassifiable: it names an instrument and a
            # share count, so it is not a cash movement - importing it as one
            # would describe a real fill to the user as a transfer and hide it
            # from the ledger comparison entirely. Report it instead.
            return None, CsvSkippedRow(
                row_number=row_number,
                reason="unrecognized_action",
                detail=(
                    f"Row for {symbol} has {raw_quantity} shares but action "
                    f"{action or '(blank)'!r} is not a recognized buy/sell/"
                    "short/cover."
                ),
            )
        # Everything else (dividends, transfers, interest, fees - no share
        # count) is imported with a null quantity, which the reconciliation
        # view classifies as non_trade: listed, flagged, never silently
        # dropped.

        # Column bounds (quantity/price are Numeric(18,8), net_amount is
        # Numeric(16,2)). An out-of-range value would otherwise escape as an
        # asyncpg NumericValueOutOfRangeError and surface as a 500 on upload;
        # a named skipped row is the honest outcome for one bad cell.
        for label, value, limit in (
            ("quantity", quantity, _MAX_NUMERIC_18_8),
            ("price", price, _MAX_NUMERIC_18_8),
            ("amount", net_amount, _MAX_NUMERIC_16_2),
        ):
            if value is not None and abs(value) >= limit:
                return None, CsvSkippedRow(
                    row_number=row_number,
                    reason="value_out_of_range",
                    detail=f"{label} {value} is too large to store.",
                )

        raw_payload = {
            "csv_row": {
                field: _cell(row, mapping, field)
                for field in _HEADERS
                if field in mapping
            }
        }

        # BOTH id schemes are namespaced by the broker account, because the
        # uniqueness constraint they land on is (user_id,
        # external_transaction_id) - it does NOT include account_hash. One user
        # can legitimately link several broker accounts (AccountLink is unique
        # on (user_id, source, account_hash)), and a CSV's own reference number
        # is only unique WITHIN the account that issued it. Without the
        # namespace, uploading two accounts' exports that happen to share a
        # small sequential reference number would silently overwrite one
        # account's transaction with the other's - the row would vanish from
        # one reconciliation view and reappear misattributed in the other.
        account_ns = hashlib.sha256(account_hash.encode("utf-8")).hexdigest()[:8]

        external_id = _cell(row, mapping, "external_id")
        if external_id:
            # Truncated to keep the whole key inside the column's 64 chars;
            # the namespace and prefix are never what gets cut.
            base = f"csv:{account_ns}:{external_id[:40]}"
        else:
            digest = hashlib.sha256(
                "|".join(
                    [
                        account_hash,
                        occurred_at.isoformat(),
                        action,
                        symbol or "",
                        str(raw_quantity if raw_quantity is not None else ""),
                        _cell(row, mapping, "price"),
                        _cell(row, mapping, "amount"),
                    ]
                ).encode("utf-8")
            ).hexdigest()[:40]
            base = f"csv:{digest}"

        # ONE disambiguation rule for BOTH id schemes. A broker reference
        # number is supposed to be unique, but nothing enforces that it is -
        # and when two different fills in one file carry the same reference,
        # an un-suffixed key makes the second row's upsert overwrite the
        # first. That loses a real fill with an EMPTY `skipped` list and an
        # imported_count that still says 2: the user is told the history was
        # recovered while the row that would have shown up as `broker_only` -
        # the entire product promise of the activity view - silently no longer
        # exists. Suffixing every repeat within the upload keeps re-uploading
        # the same file idempotent (the same rows re-derive the same
        # occurrences, in order) while never merging two distinct rows.
        seen[base] += 1
        occurrence = seen[base]
        key = base if occurrence == 1 else f"{base}:{occurrence}"

        return (
            {
                "external_transaction_id": key,
                "transaction_type": (action or "UNKNOWN")[:50],
                "symbol": symbol[:32] if symbol else None,
                "asset_type": "EQUITY" if quantity is not None else None,
                "quantity": quantity,
                "price": price,
                "net_amount": net_amount,
                "position_effect": position_effect,
                "occurred_at": occurred_at,
                "raw": raw_payload,
            },
            None,
        )
