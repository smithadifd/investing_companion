"""Reconciliation view schemas - the read-only response contracts.

Two views, both strictly read-only:

* :class:`ReconciliationResponse` - the §6 POSITIONS delta table (what Schwab
  reports holding vs what IC's ledger computes). It carries no "adopted" flag:
  the §2 adoption mutation lives at its own endpoint
  (``POST /{account_id}/reconciliation/adopt``) and is driven from the same
  rows, so the delta shown is exactly the delta adopted (WYSIWYG).
* :class:`TransactionReconciliationResponse` - the TRANSACTIONS activity view
  (imported broker transactions vs manually-entered IC trades), which answers
  the question positions reconciliation cannot: *which individual fills did I
  never write down?* Its envelope also carries the 60-day history-gap notice
  that points at the CSV recovery path.

Neither shape mutates anything.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ReconciliationPosition(BaseModel):
    """One symbol present on either side (union of Schwab + IC per §6)."""

    symbol: str
    # Schwab's raw instrument.assetType; null on an IC-only row (no Schwab
    # position in this symbol to read a type from).
    asset_type: str | None = None
    # asset_type == "EQUITY" (§5); an IC-only row (asset_type null) defaults
    # true - IC's ledger can only hold equity-like positions to begin with.
    eligible: bool
    ineligible_reason: str | None = None

    # null = that side has no position/history in this symbol for this account.
    schwab_quantity: Decimal | None = None
    ic_quantity: Decimal | None = None
    # NEVER null: an absent side is treated as 0 (§2) -
    # (schwab_quantity ?? 0) - (ic_quantity ?? 0).
    quantity_delta: Decimal

    schwab_basis: Decimal | None = None
    # FIFO-remaining-lot basis (§3); null when there are no open IC lots or
    # when ledger_inconsistent. NEVER derived from avg_cost_basis.
    ic_basis: Decimal | None = None
    basis_delta: Decimal | None = None
    # true when the open-lots walk found unmatched close quantity for this
    # symbol/account; ic_basis and basis_delta are null whenever this is true.
    ledger_inconsistent: bool = False


class ReconciliationResponse(BaseModel):
    """Account-level envelope (import recency) wrapping the position rows."""

    # Latest COMPLETE positions run's created_at; null when never_imported.
    last_import_at: datetime | None = None
    # true when the linked hash has no complete run yet (an active link can
    # predate any successful pull).
    never_imported: bool
    # Latest run newer than last_import_at with status=failed, if any (or any
    # failed run at all when never_imported) - "your last pull actually failed".
    newer_failed_import_at: datetime | None = None

    positions: list[ReconciliationPosition]


# ---------------------------------------------------------------------------
# Transactions reconciliation (activity-level, the manual-entry gap finder)
# ---------------------------------------------------------------------------
class TransactionMatch(BaseModel):
    """One reconciled activity row: a broker transaction, an IC trade, or both.

    ``status`` is the whole point of this view:

    * ``matched``     - a broker transaction and an IC trade agree on symbol,
      side and quantity within the date tolerance. Nothing to do.
    * ``broker_only`` - the broker reports a fill IC has no trade for. This is
      the manual-entry gap: activity that happened and was never written down.
    * ``ic_only``     - IC has a trade the broker does not report in this
      window. Usually a trade in a different account, one outside the imported
      window, or a hand-entry that never happened at the broker.
    * ``non_trade``   - a broker transaction with no tradeable instrument leg
      (ACH, wire, dividend, fee). Listed, never matched, never silently
      dropped - the same "show it, flag it" rule §5 applies to ineligible
      positions.
    """

    status: str

    # Broker side (null on an ic_only row).
    broker_transaction_id: int | None = None
    external_transaction_id: str | None = None
    # Which lane wrote it: "schwab_api" (live pull) or "csv_import" (recovery).
    broker_source: str | None = None
    broker_type: str | None = None
    broker_side: str | None = None
    broker_quantity: Decimal | None = None
    broker_price: Decimal | None = None
    broker_net_amount: Decimal | None = None
    broker_occurred_at: datetime | None = None

    # IC side (null on a broker_only or non_trade row).
    trade_id: int | None = None
    ic_side: str | None = None
    ic_quantity: Decimal | None = None
    ic_price: Decimal | None = None
    ic_executed_at: datetime | None = None

    # Present on both sides where known; the join key a human reads.
    symbol: str | None = None
    # Set on non_trade rows (and any row a human might otherwise think is a
    # bug), explaining why it is not matchable.
    note: str | None = None


class TransactionReconciliationResponse(BaseModel):
    """Account-level envelope for the transactions activity view."""

    # Window actually reconciled, [window_start, window_end).
    window_start: datetime
    window_end: datetime

    # Latest COMPLETE *transactions* run's created_at; null when none yet.
    last_import_at: datetime | None = None
    never_imported: bool
    newer_failed_import_at: datetime | None = None

    # True when the latest complete transactions run recorded a clamped
    # HISTORY GAP - its requested window start predated Schwab's 60-day
    # transaction horizon, so the skipped span can never be pulled from the
    # API. ``history_gap_note`` is that run's verbatim note. This is exactly
    # the condition the broker-CSV import exists to repair, so the UI reads
    # these two fields to offer the upload.
    history_gap: bool = False
    history_gap_note: str | None = None
    # Schwab's transaction-history horizon in days, echoed so the client never
    # hardcodes it (see schwab_ingestion.TRANSACTION_HISTORY_LIMIT_DAYS).
    transaction_history_limit_days: int

    matched_count: int
    broker_only_count: int
    ic_only_count: int

    transactions: list[TransactionMatch]
