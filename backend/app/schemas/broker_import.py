"""Broker import schemas - the trigger request and per-run result shapes.

Covers both import lanes that write
:class:`~app.db.models.broker_import.BrokerImportRun` rows:

* the live Schwab API pull (``source="schwab_api"``), triggered by
  ``POST /api/v1/accounts/{account_id}/import``;
* the broker-CSV upload (``source="csv_import"``, T2 sub-PR 3), the designated
  recovery path past Schwab's 60-day transaction-history horizon, triggered by
  ``POST /api/v1/accounts/{account_id}/import/csv``.

Both produce an :class:`ImportRunSummary`, deliberately: a run is a run
whichever lane wrote it, and the reconciliation views read them the same way.
No account hash is ever echoed in these shapes - it is an opaque broker token
the client has no need for on an import result.
"""

import enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ImportKindRequest(str, enum.Enum):
    """What to pull. ``both`` is the default the "Import from Schwab" button
    uses - positions drive the §6 delta table, transactions drive the activity
    reconciliation, and a user pressing one button wants both refreshed."""

    POSITIONS = "positions"
    TRANSACTIONS = "transactions"
    BOTH = "both"


class ImportTriggerRequest(BaseModel):
    """Body for the import trigger. Everything is optional/defaulted so the
    button can POST an empty object."""

    kind: ImportKindRequest = ImportKindRequest.BOTH
    source: str = Field("schwab_api", max_length=50)


class ImportRunSummary(BaseModel):
    """One :class:`BrokerImportRun` as returned to the client.

    ``notes`` is the field that carries a clamped HISTORY GAP on a *complete*
    transactions run (see ``schwab_ingestion._history_gap_note``): the run
    succeeded, but the requested window start predated Schwab's 60-day horizon
    and the skipped span is unrecoverable via the API. It is surfaced here, and
    again on the transactions reconciliation envelope, so the UI can point at
    the CSV recovery path instead of silently under-reporting activity.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    kind: str
    status: str
    window_start: datetime | None = None
    window_end: datetime | None = None
    item_count: int | None = None
    # Sanitized reason only - never a raw third-party exception's text.
    error_message: str | None = None
    notes: str | None = None
    created_at: datetime


class ImportTriggerResponse(BaseModel):
    """Result of one import trigger: one summary per kind actually pulled."""

    account_id: int
    runs: list[ImportRunSummary]


class CsvImportResponse(BaseModel):
    """Result of one broker-CSV upload (sub-PR 3).

    Per-row, not all-or-nothing at the *reporting* level (every rejected row is
    named with a reason) but strictly atomic at the *write* level: either the
    whole file's accepted rows are committed together or none are. See
    ``services/broker_csv.py``.
    """

    account_id: int
    run: ImportRunSummary
    # Rows parsed into transactions and written (inserted or updated in place
    # by the same (user_id, external_transaction_id) upsert the API pull uses).
    imported_count: int
    # Data rows the parser understood but deliberately did not import, each
    # with a human-readable reason (e.g. a non-trade cash line, a row with no
    # usable date). Never silently dropped.
    skipped: list["CsvSkippedRow"]
    # The oldest and newest occurred_at actually written, so the UI can say
    # "recovered activity from X to Y" - the whole point of the recovery path.
    earliest_occurred_at: datetime | None = None
    latest_occurred_at: datetime | None = None


class CsvSkippedRow(BaseModel):
    """One CSV data row that was parsed but not imported."""

    # 1-based index within the file's DATA rows (header excluded), so it lines
    # up with what a spreadsheet shows minus the header.
    row_number: int
    reason: str
    detail: str | None = None


CsvImportResponse.model_rebuild()
