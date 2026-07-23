"""DB-backed tests for the macro re-seed orphan-retirement mechanics.

ENV-GATED: these use the ``db`` fixture and therefore require a live
PostgreSQL/TimescaleDB test database — see tests/conftest.py. Covers three of
the sub-fixes bundled into this PR:

  * Orphan retirement (sub-fix a) only ever deletes SEED-source rows, never
    FRED/manual rows, even when their key isn't in the current spec
    (TestOrphanRetirementSourceScoping).
  * The GDP recurrence-key grain fix (sub-fix b) actually resolves a
    same-month collision at the DB layer, not just in the in-memory spec
    builder already covered in test_fred_provider.py
    (TestGdpCollisionResolvedAtDbLayer).
  * The migration/retirement ordering hazard called out in the PR body: an
    old-format GDP row must survive re-key-then-retire
    (TestMigrationOrderingSafety). The unsafe order (retire-before-rekey)
    used to wrongly delete that row -- fixed by a runtime guard in
    ``retire_orphaned_macro_events`` (see PR #223 review comment
    https://github.com/smithadifd/investing_companion/pull/223#issuecomment-5054386185)
    that now detects the pre-migration key format and aborts the whole
    retirement pass instead of deleting anything; proven below by asserting
    the guard raises and the row count is provably unchanged, not just that
    the ordering matters in the abstract.
"""

from datetime import date, time

import pytest
from sqlalchemy import func, select, text

from app.db.models.economic_event import EconomicEvent, EventSource, EventType
from app.db.migrations_sql import GDP_REKEY_UPGRADE_SQL
from app.services.data_providers.fred import MacroEventSpec, macro_recurrence_key
from app.services.economic_event import (
    EconomicEventService,
    MacroKeyMigrationPendingError,
)
from scripts.seed_macro_events import (
    MACRO_SEED_EVENT_TYPES,
    _fomc_specs,
    current_seed_keys,
    seed_statistical_specs,
)


def _cpi_spec(d: date, recurrence_key: str) -> MacroEventSpec:
    return MacroEventSpec(
        event_type=EventType.CPI.value,
        event_date=d,
        recurrence_key=recurrence_key,
        title="CPI Report",
        description="Consumer Price Index release.",
        importance="high",
        event_time=time(8, 30),
    )


def _gdp_spec(d: date, label: str, ordinal: str) -> MacroEventSpec:
    return MacroEventSpec(
        event_type=EventType.GDP.value,
        event_date=d,
        recurrence_key=macro_recurrence_key(EventType.GDP, d, ordinal=ordinal),
        title=f"GDP {label}",
        description="Gross Domestic Product report.",
        importance="high" if "Advance" in label else "medium",
        event_time=time(8, 30),
    )


class TestOrphanRetirementSourceScoping:
    """Proof (i): orphan retirement only ever deletes SEED-source rows."""

    @pytest.mark.asyncio
    async def test_only_seed_source_rows_are_deleted(self, db):
        service = EconomicEventService(db)

        await service.sync_macro_events(
            [_cpi_spec(date(2020, 1, 14), "cpi_2020_01_seed_stale")],
            source=EventSource.SEED.value,
        )
        await service.sync_macro_events(
            [_cpi_spec(date(2020, 2, 11), "cpi_2020_02_fred_stale")],
            source=EventSource.FRED.value,
        )
        await service.sync_macro_events(
            [_cpi_spec(date(2020, 3, 11), "cpi_2020_03_manual_stale")],
            source=EventSource.MANUAL.value,
        )

        # None of these three keys are in "current spec" -- all are
        # candidates by key alone. Only the SEED-source row should actually
        # be deleted; the retirement call itself is scoped to source=SEED
        # (the default).
        current_keys = {"cpi_2099_01_unrelated"}
        retired = await service.retire_orphaned_macro_events(
            current_keys, event_types=[EventType.CPI.value]
        )
        assert retired == 1

        remaining = (
            await db.execute(
                select(EconomicEvent.recurrence_key, EconomicEvent.source).where(
                    EconomicEvent.recurrence_key.in_(
                        [
                            "cpi_2020_01_seed_stale",
                            "cpi_2020_02_fred_stale",
                            "cpi_2020_03_manual_stale",
                        ]
                    )
                )
            )
        ).all()
        remaining_keys = {row.recurrence_key for row in remaining}
        assert remaining_keys == {"cpi_2020_02_fred_stale", "cpi_2020_03_manual_stale"}

    @pytest.mark.asyncio
    async def test_non_matching_event_type_is_never_a_candidate(self, db):
        """A SEED-source row of an event type NOT in ``event_types`` must
        survive even though its key isn't in ``current_keys`` -- guards
        against a pipeline that shares the SEED source tag but a different
        key scheme (e.g. scripts/seed_demo_data.py) ever being reachable."""
        service = EconomicEventService(db)
        await service.sync_macro_events(
            [
                MacroEventSpec(
                    event_type=EventType.PPI.value,
                    event_date=date(2020, 1, 1),
                    recurrence_key="ppi_2020_01_unrelated_pipeline",
                    title="PPI Report",
                    description="Producer Price Index.",
                    importance="medium",
                    event_time=time(8, 30),
                )
            ],
            source=EventSource.SEED.value,
        )

        retired = await service.retire_orphaned_macro_events(
            {"cpi_2099_01_unrelated"}, event_types=[EventType.CPI.value]
        )
        assert retired == 0

        row = (
            await db.execute(
                select(EconomicEvent).where(
                    EconomicEvent.recurrence_key == "ppi_2020_01_unrelated_pipeline"
                )
            )
        ).scalar_one_or_none()
        assert row is not None

    @pytest.mark.asyncio
    async def test_refuses_empty_current_keys(self, db):
        """An empty current_keys is almost certainly a caller bug -- refuse
        rather than delete every matching row's entire history."""
        service = EconomicEventService(db)
        with pytest.raises(ValueError):
            await service.retire_orphaned_macro_events(
                set(), event_types=[EventType.CPI.value]
            )

    @pytest.mark.asyncio
    async def test_real_current_seed_keys_never_orphans_a_fresh_reseed(self, db):
        """End-to-end sanity: seeding the real 2025+2026 spec lists and then
        immediately running retirement against current_seed_keys() must
        retire nothing -- a fresh, in-sync re-seed is a no-op."""
        service = EconomicEventService(db)
        await service.sync_macro_events(_fomc_specs(2025), source=EventSource.SEED.value)
        await service.sync_macro_events(
            seed_statistical_specs(2025), source=EventSource.SEED.value
        )

        retired = await service.retire_orphaned_macro_events(
            current_seed_keys(), MACRO_SEED_EVENT_TYPES
        )
        assert retired == 0


class TestGdpCollisionResolvedAtDbLayer:
    """Proof (ii): two different-ordinal same-month GDP prints both persist
    as distinct rows through the real upsert-through-dedup path."""

    @pytest.mark.asyncio
    async def test_april_2026_third_and_advance_both_persist(self, db):
        """The real collision this PR cites: Q4-2025 Third (Apr 9, 2026) and
        Q1-2026 Advance (Apr 30, 2026) land in the same calendar month."""
        service = EconomicEventService(db)

        third = _gdp_spec(date(2026, 4, 9), "Q4 2025 Third", ordinal="Third")
        advance = _gdp_spec(date(2026, 4, 30), "Q1 2026 Advance", ordinal="Advance")

        assert third.recurrence_key != advance.recurrence_key

        res = await service.sync_macro_events([third, advance], source=EventSource.SEED.value)
        assert res == {"created": 2, "updated": 0}

        rows = (
            await db.execute(
                select(EconomicEvent).where(
                    EconomicEvent.event_type == EventType.GDP.value,
                    EconomicEvent.event_date.in_([date(2026, 4, 9), date(2026, 4, 30)]),
                )
            )
        ).scalars().all()

        assert len(rows) == 2
        by_date = {r.event_date: r for r in rows}
        assert by_date[date(2026, 4, 9)].recurrence_key == "gdp_2026_04_third"
        assert by_date[date(2026, 4, 30)].recurrence_key == "gdp_2026_04_advance"
        assert by_date[date(2026, 4, 9)].importance == "medium"
        assert by_date[date(2026, 4, 30)].importance == "high"

    @pytest.mark.asyncio
    async def test_re_running_the_same_two_specs_updates_not_duplicates(self, db):
        service = EconomicEventService(db)
        third = _gdp_spec(date(2026, 4, 9), "Q4 2025 Third", ordinal="Third")
        advance = _gdp_spec(date(2026, 4, 30), "Q1 2026 Advance", ordinal="Advance")

        await service.sync_macro_events([third, advance], source=EventSource.SEED.value)
        res2 = await service.sync_macro_events(
            [third, advance], source=EventSource.SEED.value
        )
        assert res2 == {"created": 0, "updated": 2}

        rows = (
            await db.execute(
                select(EconomicEvent.recurrence_key).where(
                    EconomicEvent.recurrence_key.in_(
                        ["gdp_2026_04_third", "gdp_2026_04_advance"]
                    )
                )
            )
        ).scalars().all()
        assert sorted(rows) == ["gdp_2026_04_advance", "gdp_2026_04_third"]


class TestMigrationOrderingSafety:
    """Proof (iv): the migration/retirement ordering hazard called out in the
    PR body. Old-format GDP rows must survive re-key-then-retire (the safe,
    shipped order). The unsafe order -- retirement running before the
    migration -- is now caught by a runtime guard in
    ``retire_orphaned_macro_events`` (see MacroKeyMigrationPendingError):
    it detects any GDP row still on the pre-migration key format and aborts
    the ENTIRE retirement pass before the DELETE runs, rather than silently
    treating real history as an orphan."""

    async def _insert_legacy_gdp_row(self, db) -> None:
        """Simulate a row seeded by the OLD code, before the GDP grain fix:
        old month-only key, no ordinal suffix."""
        db.add(
            EconomicEvent(
                event_type=EventType.GDP.value,
                event_date=date(2025, 1, 30),
                event_time=time(8, 30),
                all_day=False,
                title="GDP Q4 2024 Advance",
                description="Gross Domestic Product report.",
                importance="high",
                source=EventSource.SEED.value,
                is_confirmed=True,
                recurrence_key="gdp_2025_01",  # old format, pre-migration
            )
        )
        await db.commit()

    @pytest.mark.asyncio
    async def test_rekey_then_retire_preserves_legacy_gdp_row(self, db):
        """The SAFE, shipped order: migration SQL runs first, so by the time
        retirement runs the row already carries the new-format key and
        matches the current spec."""
        await self._insert_legacy_gdp_row(db)

        # Standalone migration step (mirrors what `alembic upgrade head`
        # does at deploy time -- executes the EXACT SQL the real migration
        # runs, imported from the shared module, not a re-implementation).
        await db.execute(text(GDP_REKEY_UPGRADE_SQL))

        row = (
            await db.execute(
                select(EconomicEvent).where(EconomicEvent.event_date == date(2025, 1, 30))
            )
        ).scalar_one()
        assert row.recurrence_key == "gdp_2025_01_advance"

        service = EconomicEventService(db)
        retired = await service.retire_orphaned_macro_events(
            current_seed_keys(), MACRO_SEED_EVENT_TYPES
        )
        assert retired == 0

        survived = (
            await db.execute(
                select(EconomicEvent).where(EconomicEvent.event_date == date(2025, 1, 30))
            )
        ).scalar_one_or_none()
        assert survived is not None
        assert survived.recurrence_key == "gdp_2025_01_advance"

    @pytest.mark.asyncio
    async def test_retire_before_rekey_is_blocked_by_the_pre_migration_guard(
        self, db
    ):
        """The UNSAFE order: retirement invoked while the still-old-format
        key is live (migration skipped/not yet applied). Without a guard,
        this would incorrectly treat real GDP history as an orphan and
        delete it -- exactly the hazard the PR body's ordering decision
        exists to prevent (and what this test used to prove by asserting the
        row got deleted). ``retire_orphaned_macro_events`` now detects the
        pre-migration key format before its DELETE runs and aborts the whole
        pass instead: this test proves the abort, not just the danger."""
        await self._insert_legacy_gdp_row(db)

        before_count = (
            await db.execute(
                select(func.count())
                .select_from(EconomicEvent)
                .where(EconomicEvent.event_date == date(2025, 1, 30))
            )
        ).scalar_one()
        assert before_count == 1

        service = EconomicEventService(db)
        # Retirement runs directly against current_seed_keys(), which is
        # already NEW-format ("gdp_2025_01_advance", ...) because the spec
        # builder (this same PR) always emits ordinal-suffixed GDP keys now.
        # The still-old-format row ("gdp_2025_01") would be invisible to
        # that set -- the guard must fire before the DELETE ever runs.
        with pytest.raises(MacroKeyMigrationPendingError) as exc_info:
            await service.retire_orphaned_macro_events(
                current_seed_keys(), MACRO_SEED_EVENT_TYPES
            )

        # (c) actionable: names the fix and the count of affected rows.
        message = str(exc_info.value)
        assert "alembic upgrade head" in message
        assert "1" in message

        # (b) provably unchanged: same row count, same still-old-format key
        # -- nothing was deleted, nothing was mutated.
        after_count = (
            await db.execute(
                select(func.count())
                .select_from(EconomicEvent)
                .where(EconomicEvent.event_date == date(2025, 1, 30))
            )
        ).scalar_one()
        assert after_count == 1

        survivor = (
            await db.execute(
                select(EconomicEvent).where(EconomicEvent.event_date == date(2025, 1, 30))
            )
        ).scalar_one()
        assert survivor.recurrence_key == "gdp_2025_01"

    @pytest.mark.asyncio
    async def test_guard_does_not_false_positive_block_a_cpi_only_retirement(
        self, db
    ):
        """The guard must not become an overly broad block: a legacy
        old-format GDP row sitting in the DB must NOT stop a retirement pass
        that isn't even scoped to GDP (event_types doesn't include "gdp") --
        that pass can never reach a GDP row regardless (the DELETE itself is
        scoped to event_types), so gating it on an irrelevant precondition
        would be a false-positive block on legitimate operation."""
        await self._insert_legacy_gdp_row(db)

        service = EconomicEventService(db)
        await service.sync_macro_events(
            [_cpi_spec(date(2020, 1, 14), "cpi_2020_01_seed_stale")],
            source=EventSource.SEED.value,
        )

        retired = await service.retire_orphaned_macro_events(
            {"cpi_2099_01_unrelated"}, event_types=[EventType.CPI.value]
        )
        assert retired == 1

        # The unrelated legacy GDP row is untouched either way (not asserted
        # gone, not the CPI-only call's concern) -- just confirming the call
        # didn't raise.
        legacy_still_present = (
            await db.execute(
                select(EconomicEvent).where(EconomicEvent.event_date == date(2025, 1, 30))
            )
        ).scalar_one_or_none()
        assert legacy_still_present is not None
