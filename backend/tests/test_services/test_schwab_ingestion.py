"""Tests for the Schwab positions/transactions ingestion service
(T2 sub-PR 1/3, see app/services/schwab_ingestion.py).

Covers: normalization edge cases (short-position signing, missing/malformed
fields, transaction leg selection, date parsing, pagination windowing),
upsert idempotence (a re-pull never duplicates; a correction overwrites by
ID), fail-closed behavior (any failure rolls back the whole pull and leaves
the previous snapshot/rows untouched, recording a separate failed-run row
with a sanitized reason), and the "current positions" query. All Schwab
responses used here are synthetic fixtures - no live Schwab call is ever
made, and no test uses real brokerage data.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.broker_import import (
    BrokerImportRun,
    ImportedPosition,
    ImportedTransaction,
    ImportKind,
    ImportStatus,
)
from app.services.data_providers.schwab import SchwabAPIError, SchwabAuthError
from app.services.schwab_ingestion import (
    SchwabNotConnectedError,
    _date_windows,
    _normalize_position,
    _normalize_transaction,
    _primary_transfer_item,
    _safe_error_reason,
    get_connected_provider,
    get_current_positions,
    get_latest_complete_run,
    pull_positions,
    pull_transactions,
)

ACCOUNT_HASH = "HASH_TEST_0001"


# ---------------------------------------------------------------------------
# Fixtures (100% synthetic - shape verified against Schwabdev's published
# example responses, since Schwab's own API reference requires a developer
# login and could not be fetched)
# ---------------------------------------------------------------------------
def _position_fixture(**overrides) -> dict:
    position = {
        "shortQuantity": 0.0,
        "averagePrice": 150.25,
        "currentDayProfitLoss": 12.5,
        "currentDayProfitLossPercentage": 0.5,
        "longQuantity": 10.0,
        "settledLongQuantity": 10.0,
        "settledShortQuantity": 0.0,
        "instrument": {
            "assetType": "EQUITY",
            "cusip": "999999999",
            "symbol": "SYNT",
            "netChange": 1.1,
        },
        "marketValue": 1550.0,
        "maintenanceRequirement": 0.0,
        "averageLongPrice": 150.25,
        "taxLotAverageLongPrice": 150.25,
        "longOpenProfitLoss": 47.5,
        "previousSessionLongQuantity": 10.0,
        "currentDayCost": 0.0,
    }
    position.update(overrides)
    return position


def _transaction_fixture(**overrides) -> dict:
    transaction = {
        "activityId": 1000000001,
        "time": "2026-06-01T14:32:00+0000",
        "type": "TRADE",
        "status": "VALID",
        "subAccount": "MARGIN",
        "tradeDate": "2026-06-01T14:32:00+0000",
        "positionId": 5555555,
        "orderId": 6666666666666,
        "netAmount": -1502.30,
        "transferItems": [
            {
                "instrument": {
                    "assetType": "CURRENCY",
                    "status": "ACTIVE",
                    "symbol": "CURRENCY_USD",
                    "description": "USD currency",
                    "instrumentId": 1,
                    "closingPrice": 0.0,
                },
                "amount": -1502.30,
                "cost": 1502.30,
                "feeType": "COMMISSION",
            },
            {
                "instrument": {
                    "assetType": "EQUITY",
                    "status": "ACTIVE",
                    "symbol": "SYNT",
                    "instrumentId": 88888888,
                    "closingPrice": 150.23,
                },
                "amount": 10.0,
                "cost": 1502.30,
                "price": 150.23,
                "positionEffect": "OPENING",
            },
        ],
    }
    transaction.update(overrides)
    return transaction


class _StubResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _fresh_wrapped_token() -> dict:
    return {"creation_timestamp": int(time.time()), "token": {"access_token": "x"}}


async def _connect_schwab(db, user, monkeypatch):
    """Configure the server + connect a fresh (non-expired) token for user."""
    from app.core.config import settings
    from app.services.settings import SettingsService

    monkeypatch.setattr(settings, "SCHWAB_APP_KEY", "k")
    monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "s")
    monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://x/cb")

    service = SettingsService(db)
    await service.set_setting(
        SettingsService.SCHWAB_TOKEN, json.dumps(_fresh_wrapped_token()), user.id
    )


class _FakeProvider:
    """A minimal stand-in for SchwabProvider that records calls and serves
    pre-scripted position/transaction pages - used so pull_positions/
    pull_transactions can be tested without going through the real token/
    client-construction path (that path is covered by
    TestGetConnectedProvider below and by test_schwab_provider.py)."""

    def __init__(self, positions=None, transaction_pages=None, raise_on_call=None):
        self._positions = positions if positions is not None else []
        self._transaction_pages = list(transaction_pages or [])
        self._raise_on_call = raise_on_call
        self.transaction_calls: list[tuple] = []
        self.closed = False

    async def get_positions(self, account_hash):
        if self._raise_on_call == "positions":
            raise SchwabAPIError("synthetic failure")
        return self._positions

    async def get_transactions(self, account_hash, start_date, end_date, transaction_types=None):
        self.transaction_calls.append((account_hash, start_date, end_date))
        if self._raise_on_call == "transactions" and len(self.transaction_calls) >= (
            self._raise_on_call_at if isinstance(self._raise_on_call_at, int) else 1
        ):
            raise SchwabAPIError("synthetic failure")
        if not self._transaction_pages:
            return []
        return self._transaction_pages.pop(0)

    async def aclose(self):
        self.closed = True


@pytest.fixture
def patch_provider(monkeypatch):
    """Patch get_connected_provider to return a given _FakeProvider."""

    def _patch(fake_provider):
        async def _fake_get_connected_provider(db, user_id):
            return fake_provider

        monkeypatch.setattr(
            "app.services.schwab_ingestion.get_connected_provider",
            _fake_get_connected_provider,
        )
        return fake_provider

    return _patch


# ---------------------------------------------------------------------------
# get_connected_provider
# ---------------------------------------------------------------------------
class TestGetConnectedProvider:
    async def test_not_configured_raises(self, db, test_user):
        with pytest.raises(SchwabNotConnectedError):
            await get_connected_provider(db, test_user.id)

    async def test_configured_without_token_raises(self, db, test_user, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "SCHWAB_APP_KEY", "k")
        monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "s")
        monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://x/cb")

        with pytest.raises(SchwabNotConnectedError):
            await get_connected_provider(db, test_user.id)

    async def test_expired_token_raises(self, db, test_user, monkeypatch):
        from app.core.config import settings
        from app.services.settings import SettingsService

        monkeypatch.setattr(settings, "SCHWAB_APP_KEY", "k")
        monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "s")
        monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://x/cb")

        service = SettingsService(db)
        await service.set_setting(
            SettingsService.SCHWAB_TOKEN,
            json.dumps({"creation_timestamp": int(time.time()) - 8 * 86400, "token": {}}),
            test_user.id,
        )

        with pytest.raises(SchwabNotConnectedError):
            await get_connected_provider(db, test_user.id)

    async def test_connected_returns_bound_provider(self, db, test_user, monkeypatch):
        from app.services.data_providers.schwab import SchwabProvider

        await _connect_schwab(db, test_user, monkeypatch)
        provider = await get_connected_provider(db, test_user.id)
        assert isinstance(provider, SchwabProvider)
        assert provider.user_id == test_user.id


# ---------------------------------------------------------------------------
# Normalization: positions
# ---------------------------------------------------------------------------
class TestNormalizePosition:
    def test_long_position_signed_quantity_positive(self):
        result = _normalize_position(_position_fixture(longQuantity=10.0, shortQuantity=0.0))
        assert result["quantity"] == Decimal("10")
        assert result["long_quantity"] == Decimal("10")
        assert result["short_quantity"] == Decimal("0")

    def test_short_position_signed_quantity_negative(self):
        result = _normalize_position(
            _position_fixture(longQuantity=0.0, shortQuantity=25.0, symbol="SHRT")
        )
        assert result["quantity"] == Decimal("-25")
        assert result["short_quantity"] == Decimal("25")

    def test_missing_symbol_raises(self):
        bad = _position_fixture()
        bad["instrument"] = {"assetType": "EQUITY"}
        with pytest.raises(SchwabAPIError):
            _normalize_position(bad)

    def test_unknown_asset_type_preserved(self):
        result = _normalize_position(
            _position_fixture(instrument={"assetType": "FUTURE", "symbol": "/ES"})
        )
        assert result["asset_type"] == "FUTURE"

    def test_missing_asset_type_defaults_to_unknown(self):
        result = _normalize_position(
            _position_fixture(instrument={"symbol": "NOTYPE"})
        )
        assert result["asset_type"] == "UNKNOWN"

    def test_quantities_are_decimal_not_float(self):
        result = _normalize_position(_position_fixture())
        assert isinstance(result["quantity"], Decimal)
        assert isinstance(result["average_price"], Decimal)

    def test_raw_payload_preserved(self):
        raw = _position_fixture()
        result = _normalize_position(raw)
        assert result["raw"] == raw


# ---------------------------------------------------------------------------
# Normalization: transactions
# ---------------------------------------------------------------------------
class TestPrimaryTransferItem:
    def test_picks_the_leg_with_position_effect(self):
        txn = _transaction_fixture()
        primary = _primary_transfer_item(txn["transferItems"])
        assert primary["instrument"]["symbol"] == "SYNT"

    def test_none_when_no_leg_has_position_effect(self):
        # e.g. an ACH/cash transaction: only currency/fee-style legs.
        items = [
            {"instrument": {"assetType": "CURRENCY", "symbol": "CURRENCY_USD"}, "amount": 500.0}
        ]
        assert _primary_transfer_item(items) is None

    def test_empty_or_none_is_none(self):
        assert _primary_transfer_item([]) is None
        assert _primary_transfer_item(None) is None


class TestNormalizeTransaction:
    def test_happy_path(self):
        result = _normalize_transaction(_transaction_fixture())
        assert result["external_transaction_id"] == "1000000001"
        assert result["transaction_type"] == "TRADE"
        assert result["symbol"] == "SYNT"
        assert result["asset_type"] == "EQUITY"
        assert result["quantity"] == Decimal("10")
        assert result["price"] == Decimal("150.23")
        assert result["position_effect"] == "OPENING"
        assert result["net_amount"] == Decimal("-1502.3")
        assert result["order_id"] == "6666666666666"
        assert result["occurred_at"] == datetime(2026, 6, 1, 14, 32, tzinfo=timezone.utc)

    def test_missing_activity_id_raises(self):
        bad = _transaction_fixture()
        del bad["activityId"]
        with pytest.raises(SchwabAPIError):
            _normalize_transaction(bad)

    def test_missing_date_raises(self):
        bad = _transaction_fixture()
        del bad["tradeDate"]
        del bad["time"]
        with pytest.raises(SchwabAPIError):
            _normalize_transaction(bad)

    def test_falls_back_to_time_when_trade_date_missing(self):
        bad = _transaction_fixture()
        del bad["tradeDate"]
        bad["time"] = "2026-06-02T09:00:00+0000"
        result = _normalize_transaction(bad)
        assert result["occurred_at"] == datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc)

    def test_non_trade_transaction_with_no_primary_leg(self):
        """ACH-style transaction: no equity leg, symbol/price/etc all None,
        but normalization must not raise."""
        txn = _transaction_fixture(
            type="ACH_RECEIPT",
            transferItems=[
                {
                    "instrument": {"assetType": "CURRENCY", "symbol": "CURRENCY_USD"},
                    "amount": 500.0,
                }
            ],
        )
        result = _normalize_transaction(txn)
        assert result["symbol"] is None
        assert result["asset_type"] is None
        assert result["quantity"] is None
        assert result["price"] is None
        assert result["position_effect"] is None
        assert result["transaction_type"] == "ACH_RECEIPT"

    def test_order_id_stringified(self):
        result = _normalize_transaction(_transaction_fixture(orderId=42))
        assert result["order_id"] == "42"

    def test_missing_order_id_is_none(self):
        bad = _transaction_fixture()
        del bad["orderId"]
        result = _normalize_transaction(bad)
        assert result["order_id"] is None

    def test_missing_type_defaults_to_unknown(self):
        bad = _transaction_fixture()
        del bad["type"]
        result = _normalize_transaction(bad)
        assert result["transaction_type"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# _date_windows (pagination/chunking)
# ---------------------------------------------------------------------------
class TestDateWindows:
    def test_empty_range_yields_nothing(self):
        now = datetime(2026, 7, 1, tzinfo=timezone.utc)
        assert list(_date_windows(now, now)) == []
        assert list(_date_windows(now, now - timedelta(days=1))) == []

    def test_within_cap_yields_one_chunk(self):
        start = datetime(2026, 6, 1, tzinfo=timezone.utc)
        end = datetime(2026, 6, 20, tzinfo=timezone.utc)
        windows = list(_date_windows(start, end, max_days=60))
        assert windows == [(start, end)]

    def test_exactly_at_cap_yields_one_chunk(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=60)
        windows = list(_date_windows(start, end, max_days=60))
        assert windows == [(start, end)]

    def test_wide_range_chunks_without_gaps_or_overlap(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=130)
        windows = list(_date_windows(start, end, max_days=60))
        assert len(windows) == 3
        # Contiguous: each chunk's end is the next chunk's start.
        assert windows[0][0] == start
        assert windows[0][1] == windows[1][0]
        assert windows[1][1] == windows[2][0]
        assert windows[2][1] == end
        # No chunk exceeds the cap.
        for chunk_start, chunk_end in windows:
            assert (chunk_end - chunk_start) <= timedelta(days=60)


# ---------------------------------------------------------------------------
# _safe_error_reason
# ---------------------------------------------------------------------------
class TestSafeErrorReason:
    def test_first_party_schwab_api_error_keeps_message(self):
        reason = _safe_error_reason(SchwabAPIError("Schwab get_account returned HTTP 500"))
        assert "SchwabAPIError" in reason
        assert "HTTP 500" in reason

    def test_first_party_auth_error_keeps_message(self):
        reason = _safe_error_reason(SchwabAuthError("Schwab rejected the request"))
        assert "SchwabAuthError" in reason

    def test_generic_exception_message_is_never_persisted(self):
        exc = Exception("leaked accountNumber=99999999 sensitive detail")
        reason = _safe_error_reason(exc)
        assert reason == "Exception"
        assert "99999999" not in reason
        assert "accountNumber" not in reason

    def test_generic_db_style_exception_message_is_never_persisted(self):
        class FakeIntegrityError(Exception):
            pass

        exc = FakeIntegrityError("duplicate key value violates unique constraint ...")
        reason = _safe_error_reason(exc)
        assert reason == "FakeIntegrityError"


# ---------------------------------------------------------------------------
# pull_positions
# ---------------------------------------------------------------------------
class TestPullPositions:
    async def test_happy_path_creates_run_and_positions(self, db, test_user, patch_provider):
        fake = patch_provider(
            _FakeProvider(positions=[_position_fixture(), _position_fixture(
                instrument={"assetType": "EQUITY", "cusip": "1", "symbol": "OTHR"}
            )])
        )
        run = await pull_positions(db, test_user.id, ACCOUNT_HASH)

        assert run.status == ImportStatus.COMPLETE
        assert run.kind == ImportKind.POSITIONS
        assert run.item_count == 2
        assert fake.closed is True

        rows = (
            await db.execute(
                select(ImportedPosition).where(ImportedPosition.import_run_id == run.id)
            )
        ).scalars().all()
        assert len(rows) == 2
        symbols = {r.symbol for r in rows}
        assert symbols == {"SYNT", "OTHR"}

    async def test_short_position_persists_negative_quantity(self, db, test_user, patch_provider):
        patch_provider(
            _FakeProvider(
                positions=[
                    _position_fixture(longQuantity=0.0, shortQuantity=5.0, symbol="SHRT")
                ]
            )
        )
        run = await pull_positions(db, test_user.id, ACCOUNT_HASH)
        rows = (
            await db.execute(
                select(ImportedPosition).where(ImportedPosition.import_run_id == run.id)
            )
        ).scalars().all()
        assert rows[0].quantity == Decimal("-5")

    async def test_repull_creates_new_run_not_upsert(self, db, test_user, patch_provider):
        patch_provider(_FakeProvider(positions=[_position_fixture()]))
        run1 = await pull_positions(db, test_user.id, ACCOUNT_HASH)

        patch_provider(_FakeProvider(positions=[_position_fixture(marketValue=9999.0)]))
        run2 = await pull_positions(db, test_user.id, ACCOUNT_HASH)

        assert run1.id != run2.id
        all_runs = (
            await db.execute(
                select(BrokerImportRun).where(
                    BrokerImportRun.user_id == test_user.id,
                    BrokerImportRun.kind == ImportKind.POSITIONS,
                )
            )
        ).scalars().all()
        assert len(all_runs) == 2

        current = await get_current_positions(db, test_user.id, ACCOUNT_HASH)
        assert len(current) == 1
        assert current[0].market_value == Decimal("9999.00")

    async def test_failure_writes_failed_run_and_no_positions(self, db, test_user, patch_provider):
        patch_provider(_FakeProvider(raise_on_call="positions"))

        with pytest.raises(SchwabAPIError):
            await pull_positions(db, test_user.id, ACCOUNT_HASH)

        runs = (
            await db.execute(
                select(BrokerImportRun).where(BrokerImportRun.user_id == test_user.id)
            )
        ).scalars().all()
        assert len(runs) == 1
        assert runs[0].status == ImportStatus.FAILED
        assert runs[0].error_message is not None
        assert "SchwabAPIError" in runs[0].error_message

        positions = (
            await db.execute(
                select(ImportedPosition).where(ImportedPosition.user_id == test_user.id)
            )
        ).scalars().all()
        assert positions == []

    async def test_failure_after_success_leaves_previous_snapshot_untouched(
        self, db, test_user, patch_provider
    ):
        patch_provider(_FakeProvider(positions=[_position_fixture()]))
        good_run = await pull_positions(db, test_user.id, ACCOUNT_HASH)

        patch_provider(_FakeProvider(raise_on_call="positions"))
        with pytest.raises(SchwabAPIError):
            await pull_positions(db, test_user.id, ACCOUNT_HASH)

        # The prior complete run and its positions are still exactly there.
        current = await get_current_positions(db, test_user.id, ACCOUNT_HASH)
        assert len(current) == 1
        latest_complete = await get_latest_complete_run(db, test_user.id, ACCOUNT_HASH)
        assert latest_complete.id == good_run.id


# ---------------------------------------------------------------------------
# get_latest_complete_run / get_current_positions
# ---------------------------------------------------------------------------
class TestCurrentPositionsQuery:
    async def test_no_runs_returns_empty(self, db, test_user):
        assert await get_latest_complete_run(db, test_user.id, ACCOUNT_HASH) is None
        assert await get_current_positions(db, test_user.id, ACCOUNT_HASH) == []

    async def test_only_failed_runs_returns_empty(self, db, test_user, patch_provider):
        patch_provider(_FakeProvider(raise_on_call="positions"))
        with pytest.raises(SchwabAPIError):
            await pull_positions(db, test_user.id, ACCOUNT_HASH)

        assert await get_latest_complete_run(db, test_user.id, ACCOUNT_HASH) is None
        assert await get_current_positions(db, test_user.id, ACCOUNT_HASH) == []

    async def test_different_accounts_are_isolated(self, db, test_user, patch_provider):
        patch_provider(_FakeProvider(positions=[_position_fixture()]))
        await pull_positions(db, test_user.id, "HASH_ONE")

        assert await get_current_positions(db, test_user.id, "HASH_TWO") == []
        assert len(await get_current_positions(db, test_user.id, "HASH_ONE")) == 1


# ---------------------------------------------------------------------------
# pull_transactions
# ---------------------------------------------------------------------------
class TestPullTransactions:
    async def test_happy_path_inserts_transactions(self, db, test_user, patch_provider):
        patch_provider(
            _FakeProvider(
                transaction_pages=[
                    [_transaction_fixture(), _transaction_fixture(activityId=2)]
                ]
            )
        )
        run = await pull_transactions(
            db,
            test_user.id,
            ACCOUNT_HASH,
            start_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 6, 30, tzinfo=timezone.utc),
        )

        assert run.status == ImportStatus.COMPLETE
        assert run.item_count == 2

        rows = (
            await db.execute(
                select(ImportedTransaction).where(ImportedTransaction.user_id == test_user.id)
            )
        ).scalars().all()
        assert len(rows) == 2
        assert {r.external_transaction_id for r in rows} == {"1000000001", "2"}
        for row in rows:
            assert row.raw.get("accountNumber") is None or "accountNumber" not in row.raw

    async def test_repull_same_window_does_not_duplicate(self, db, test_user, patch_provider):
        window = dict(
            start_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 6, 30, tzinfo=timezone.utc),
        )
        patch_provider(_FakeProvider(transaction_pages=[[_transaction_fixture()]]))
        await pull_transactions(db, test_user.id, ACCOUNT_HASH, **window)

        patch_provider(_FakeProvider(transaction_pages=[[_transaction_fixture()]]))
        await pull_transactions(db, test_user.id, ACCOUNT_HASH, **window)

        rows = (
            await db.execute(
                select(ImportedTransaction).where(ImportedTransaction.user_id == test_user.id)
            )
        ).scalars().all()
        assert len(rows) == 1

    async def test_correction_overwrites_by_id(self, db, test_user, patch_provider):
        window = dict(
            start_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 6, 30, tzinfo=timezone.utc),
        )
        patch_provider(
            _FakeProvider(transaction_pages=[[_transaction_fixture(netAmount=-1502.30)]])
        )
        await pull_transactions(db, test_user.id, ACCOUNT_HASH, **window)

        patch_provider(
            _FakeProvider(transaction_pages=[[_transaction_fixture(netAmount=-1400.00)]])
        )
        await pull_transactions(db, test_user.id, ACCOUNT_HASH, **window)

        rows = (
            await db.execute(
                select(ImportedTransaction).where(ImportedTransaction.user_id == test_user.id)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].net_amount == Decimal("-1400.00")

    async def test_default_window_is_30_days_when_no_prior_transactions(
        self, db, test_user, patch_provider
    ):
        fake = patch_provider(_FakeProvider(transaction_pages=[[]]))
        before = datetime.now(timezone.utc)
        await pull_transactions(db, test_user.id, ACCOUNT_HASH)
        after = datetime.now(timezone.utc)

        assert len(fake.transaction_calls) == 1
        _, called_start, called_end = fake.transaction_calls[0]
        expected_start_floor = before - timedelta(days=30)
        expected_start_ceiling = after - timedelta(days=30)
        assert expected_start_floor <= called_start <= expected_start_ceiling

    async def test_default_window_starts_at_cursor_when_transactions_exist(
        self, db, test_user, patch_provider
    ):
        patch_provider(
            _FakeProvider(transaction_pages=[[_transaction_fixture()]])
        )
        first_run = await pull_transactions(
            db,
            test_user.id,
            ACCOUNT_HASH,
            start_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )
        assert first_run.item_count == 1

        fake2 = patch_provider(_FakeProvider(transaction_pages=[[]]))
        await pull_transactions(db, test_user.id, ACCOUNT_HASH)

        _, called_start, _ = fake2.transaction_calls[0]
        # Cursor = the stored transaction's occurred_at (2026-06-01T14:32:00Z).
        assert called_start == datetime(2026, 6, 1, 14, 32, tzinfo=timezone.utc)

    async def test_wide_window_makes_multiple_chunked_calls(self, db, test_user, patch_provider):
        fake = patch_provider(_FakeProvider(transaction_pages=[[], [], []]))
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=130)
        await pull_transactions(db, test_user.id, ACCOUNT_HASH, start_date=start, end_date=end)

        assert len(fake.transaction_calls) == 3

    async def test_failure_mid_pagination_rolls_back_all_chunks(
        self, db, test_user, patch_provider
    ):
        fake = _FakeProvider(
            transaction_pages=[[_transaction_fixture()], []],
            raise_on_call="transactions",
        )
        fake._raise_on_call_at = 2  # succeed on chunk 1, fail on chunk 2
        patch_provider(fake)

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=130)
        with pytest.raises(SchwabAPIError):
            await pull_transactions(db, test_user.id, ACCOUNT_HASH, start_date=start, end_date=end)

        rows = (
            await db.execute(
                select(ImportedTransaction).where(ImportedTransaction.user_id == test_user.id)
            )
        ).scalars().all()
        assert rows == []

        runs = (
            await db.execute(
                select(BrokerImportRun).where(
                    BrokerImportRun.user_id == test_user.id,
                    BrokerImportRun.kind == ImportKind.TRANSACTIONS,
                )
            )
        ).scalars().all()
        assert len(runs) == 1
        assert runs[0].status == ImportStatus.FAILED

    async def test_zero_gap_window_is_a_successful_noop(self, db, test_user, patch_provider):
        """Cursor already caught up to 'now' - a valid complete run with
        zero items, not a failure."""
        now = datetime.now(timezone.utc)
        patch_provider(_FakeProvider(transaction_pages=[]))
        run = await pull_transactions(
            db, test_user.id, ACCOUNT_HASH, start_date=now, end_date=now
        )
        assert run.status == ImportStatus.COMPLETE
        assert run.item_count == 0


# ---------------------------------------------------------------------------
# Model-level constraint checks
# ---------------------------------------------------------------------------
class TestModelConstraints:
    async def test_duplicate_symbol_within_run_violates_unique_constraint(self, db, test_user):
        run = BrokerImportRun(
            user_id=test_user.id,
            account_hash=ACCOUNT_HASH,
            source="schwab_api",
            kind=ImportKind.POSITIONS,
            status=ImportStatus.COMPLETE,
            item_count=2,
        )
        db.add(run)
        await db.flush()

        kwargs = _normalize_position(_position_fixture())
        db.add(
            ImportedPosition(
                import_run_id=run.id,
                user_id=test_user.id,
                account_hash=ACCOUNT_HASH,
                source="schwab_api",
                **kwargs,
            )
        )
        await db.flush()
        db.add(
            ImportedPosition(
                import_run_id=run.id,
                user_id=test_user.id,
                account_hash=ACCOUNT_HASH,
                source="schwab_api",
                **kwargs,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_duplicate_external_transaction_id_for_user_violates_unique_constraint(
        self, db, test_user
    ):
        kwargs = _normalize_transaction(_transaction_fixture())
        db.add(
            ImportedTransaction(
                user_id=test_user.id, account_hash=ACCOUNT_HASH, source="schwab_api", **kwargs
            )
        )
        await db.flush()
        db.add(
            ImportedTransaction(
                user_id=test_user.id, account_hash=ACCOUNT_HASH, source="schwab_api", **kwargs
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
