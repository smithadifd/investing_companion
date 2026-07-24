"""Reconciliation view schemas - the read-only §6 response contract.

Strictly read-only: this shape displays deltas between what Schwab reports and
what IC's ledger holds. It carries NO adoption/mutation surface (no "adopted"
flag, no Adopt action) - those need the §2 Trade-provenance columns and belong
to a later wave.
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
