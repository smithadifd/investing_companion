"""Adoption endpoint schemas - the §2 mutation response contract.

``POST /api/v1/accounts/{account_id}/reconciliation/adopt`` turns the read-only
§6 reconciliation delta into synthetic, provenance-stamped Trades. Its response
is a per-row report (NOT all-or-nothing): each equity is adopted on its own
reused ``create_trade`` commit, so one row failing/skipping never rolls back the
others. Rows split three ways:

* ``adopted``  - a synthetic BUY/SELL was written (``created``) or already
  existed for this (account, equity, run) and was left alone
  (``already_adopted``, the replay/race-safe outcome).
* ``skipped``  - a row that was NOT adopted and carries a reason
  (ineligible asset class §5, manual-review §2, or no usable basis §3).
* exact matches (delta == 0) are no-ops and appear in neither list.
"""

from decimal import Decimal

from pydantic import BaseModel


class AdoptedTrade(BaseModel):
    """One equity for which adoption wrote (or found) a synthetic trade."""

    symbol: str
    equity_id: int
    trade_type: str          # "buy" (delta > 0) or "sell" (delta < 0)
    quantity: Decimal        # abs(delta)
    price: Decimal | None = None      # Schwab avg or quote fallback; null on already_adopted
    basis_is_estimated: bool = False  # true = quote-price placeholder (§3)
    status: str              # "created" | "already_adopted"
    trade_id: int | None = None       # the synthetic trade's id


class SkippedPosition(BaseModel):
    """One reconciliation row that was NOT adopted, with the reason."""

    symbol: str
    quantity_delta: Decimal
    # "ineligible" (asset class §5) | "manual_review" (§2 short/zero-crossing)
    # | "no_basis" (§3: no Schwab avg and no current quote) | "unresolved_equity"
    reason: str
    detail: str


class AdoptionResponse(BaseModel):
    """Result of one adopt call against the account's latest complete run."""

    account_id: int
    # The BrokerImportRun the deltas were reconciled against (stamped onto every
    # synthetic trade as source_import_run_id).
    source_import_run_id: int
    adopted: list[AdoptedTrade]
    skipped: list[SkippedPosition]
