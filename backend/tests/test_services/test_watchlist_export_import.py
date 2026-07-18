"""Watchlist export/import round-trip: catalyst_tags + track_calendar.

Mirrors the entry_zones round-trip fix (PR #207) for the two fields that
were still silently dropped by WatchlistExportItem/WatchlistImportItem and
their export_watchlist/import_watchlist service methods.

Note on the read-back pattern: ``import_watchlist()``'s own immediate return
value cannot be trusted for asserting on ``items`` in a test session - a
pre-existing identity-map staleness issue (unrelated to this fix, present in
the original code before any of these changes) means the ``Watchlist.items``
collection gets cached as empty by the ``db.refresh(watchlist)`` call earlier
in the same method, and a later `get_watchlist()` in the *same* session
returns that same stale, empty collection rather than re-querying. Calling
``db.expire_all()`` before reading back (as done here) forces a fresh load
and is exactly what a second request against a fresh DB session would see.
See the PR description / builder report for the full writeup - it's flagged
as an out-of-scope escalation, not fixed here.
"""

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.watchlist import (
    MAX_CATALYST_TAGS,
    WatchlistImport,
    WatchlistImportItem,
)
from app.services.watchlist import WatchlistService
from tests.factories import (
    create_test_equity,
    create_test_watchlist,
    create_test_watchlist_item,
)


async def _import_and_reload(db: AsyncSession, service: WatchlistService, data: WatchlistImport):
    """Import, then force a fresh read-back within the same session.

    See module docstring: import_watchlist()'s own return can't be trusted
    for `.items` in-session due to a pre-existing, unrelated staleness bug.
    """
    result = await service.import_watchlist(data)
    db.expire_all()
    return await service.get_watchlist(result.id, include_quotes=False)


class TestExportIncludesBothFields:
    async def test_export_carries_catalyst_tags_and_track_calendar(
        self, db: AsyncSession
    ):
        equity = await create_test_equity(db, symbol="EXP1")
        wl = await create_test_watchlist(db, name="Export WL")
        await create_test_watchlist_item(
            db,
            wl,
            equity,
            catalyst_tags=["uranium restart", "carry unwind"],
            track_calendar=False,
        )

        service = WatchlistService(db)
        export = await service.export_watchlist(wl.id)

        assert export is not None
        assert len(export.items) == 1
        item = export.items[0]
        assert item.catalyst_tags == ["uranium restart", "carry unwind"]
        assert item.track_calendar is False

    async def test_export_defaults_absent_tags_to_none_and_true_calendar(
        self, db: AsyncSession
    ):
        equity = await create_test_equity(db, symbol="EXP2")
        wl = await create_test_watchlist(db, name="Export WL 2")
        await create_test_watchlist_item(db, wl, equity)

        service = WatchlistService(db)
        export = await service.export_watchlist(wl.id)

        item = export.items[0]
        assert item.catalyst_tags is None
        assert item.track_calendar is True


class TestImportSetsBothFields:
    async def test_import_persists_catalyst_tags_and_track_calendar(
        self, db: AsyncSession
    ):
        await create_test_equity(db, symbol="IMP1")
        service = WatchlistService(db)

        result = await _import_and_reload(
            db,
            service,
            WatchlistImport(
                name="Imported",
                items=[
                    WatchlistImportItem(
                        symbol="IMP1",
                        catalyst_tags=["Uranium Restart", " uranium restart "],
                        track_calendar=False,
                    )
                ],
            ),
        )

        assert len(result.items) == 1
        item = result.items[0]
        # Normalized/deduped by the shared validator.
        assert item.catalyst_tags == ["uranium restart"]
        assert item.track_calendar is False

    async def test_import_without_fields_defaults_to_null_and_true(
        self, db: AsyncSession
    ):
        """Old export files omitting both fields must still import cleanly:
        catalyst_tags -> NULL, track_calendar -> True (the model default)."""
        await create_test_equity(db, symbol="IMP2")
        service = WatchlistService(db)

        result = await _import_and_reload(
            db,
            service,
            WatchlistImport(
                name="Imported Old Format",
                items=[WatchlistImportItem(symbol="IMP2")],
            ),
        )

        item = result.items[0]
        assert item.catalyst_tags == []  # response schema defaults None -> []
        assert item.track_calendar is True


class TestExportImportRoundTrip:
    async def test_round_trip_preserves_non_default_values(self, db: AsyncSession):
        """The exact case the old code silently destroyed: a non-default
        track_calendar=False and a non-empty catalyst_tags list must survive
        an export -> import round-trip."""
        equity = await create_test_equity(db, symbol="RT1")
        source_wl = await create_test_watchlist(db, name="Source WL")
        await create_test_watchlist_item(
            db,
            source_wl,
            equity,
            catalyst_tags=["natgas", "carry unwind"],
            track_calendar=False,
        )

        service = WatchlistService(db)
        exported = await service.export_watchlist(source_wl.id)

        # Round-trip through the schema exactly like an uploaded JSON file
        # would (WatchlistExportItem -> dict -> WatchlistImportItem).
        import_items = [
            WatchlistImportItem(
                symbol=item.symbol,
                notes=item.notes,
                target_price=item.target_price,
                thesis=item.thesis,
                entry_zones=item.entry_zones,
                catalyst_tags=item.catalyst_tags,
                track_calendar=item.track_calendar,
            )
            for item in exported.items
        ]
        imported = await _import_and_reload(
            db, service, WatchlistImport(name="Round Trip", items=import_items)
        )

        item = imported.items[0]
        assert item.catalyst_tags == ["natgas", "carry unwind"]
        assert item.track_calendar is False


class TestImportSchemaCatalystTagsValidation:
    """WatchlistImportItem must apply the SAME catalyst_tags validation as
    the CRUD schemas (WatchlistItemBase) - normalize/dedup/cap - not a bypass."""

    def test_whitespace_and_case_normalized(self):
        item = WatchlistImportItem(
            symbol="AAA", catalyst_tags=["Uranium Restart", " URANIUM restart "]
        )
        assert item.catalyst_tags == ["uranium restart"]

    def test_dedup_runs_before_count_cap(self):
        # 12 raw tags that dedupe to 2 must not 422 on the raw count.
        item = WatchlistImportItem(symbol="AAA", catalyst_tags=["a", "b"] * 6)
        assert item.catalyst_tags == ["a", "b"]

    def test_empty_list_stays_empty(self):
        item = WatchlistImportItem(symbol="AAA", catalyst_tags=[])
        assert item.catalyst_tags == []

    def test_all_whitespace_tags_drop_to_empty(self):
        item = WatchlistImportItem(symbol="AAA", catalyst_tags=["   ", ""])
        assert item.catalyst_tags == []

    def test_too_many_distinct_tags_rejected(self):
        with pytest.raises(ValidationError):
            WatchlistImportItem(
                symbol="AAA",
                catalyst_tags=[f"tag{i}" for i in range(MAX_CATALYST_TAGS + 1)],
            )

    def test_absent_catalyst_tags_stays_none(self):
        item = WatchlistImportItem(symbol="AAA")
        assert item.catalyst_tags is None
