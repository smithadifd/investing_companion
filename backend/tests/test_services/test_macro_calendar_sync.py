"""DB-backed tests for macro-calendar upsert-through-dedup.

ENV-GATED: these use the ``db`` fixture and therefore require a live
PostgreSQL/TimescaleDB test database — see ``tests/conftest.py`` /
``tests/db_naming.py`` for how it's named and provisioned. They do not run
in a bare CI/dev shell without that DB — the pure feed-parser / fallback
logic is covered network-and-DB-free in ``test_fred_provider.py``.
"""

from datetime import date, time

import pytest
from sqlalchemy import func, select

from app.db.models.economic_event import EconomicEvent, EventSource, EventType
from app.services.data_providers.fred import MacroEventSpec
from app.services.economic_event import EconomicEventService


def _cpi_spec(d: date) -> MacroEventSpec:
    return MacroEventSpec(
        event_type=EventType.CPI.value,
        event_date=d,
        recurrence_key=f"cpi_{d.year}_{d.month:02d}",
        title="CPI Report",
        description="Consumer Price Index release.",
        importance="high",
        event_time=time(8, 30),
    )


@pytest.mark.asyncio
async def test_upsert_creates_then_dedups(db):
    service = EconomicEventService(db)

    res1 = await service.sync_macro_events([_cpi_spec(date(2027, 1, 14))])
    assert res1 == {"created": 1, "updated": 0}

    # Re-running the same recurrence_key must not create a second row.
    res2 = await service.sync_macro_events([_cpi_spec(date(2027, 1, 14))])
    assert res2 == {"created": 0, "updated": 1}

    count = await db.scalar(
        select(func.count(EconomicEvent.id)).where(
            EconomicEvent.recurrence_key == "cpi_2027_01"
        )
    )
    assert count == 1


@pytest.mark.asyncio
async def test_moved_date_self_heals_in_place(db):
    """A corrected/moved date for the same month updates the existing row —
    the self-healing behavior issue 015 asked for (no duplicate, no stale date)."""
    service = EconomicEventService(db)

    await service.sync_macro_events([_cpi_spec(date(2027, 2, 11))])
    # FRED later publishes a moved date within the same month.
    await service.sync_macro_events(
        [_cpi_spec(date(2027, 2, 12))], source=EventSource.FRED.value
    )

    rows = (
        await db.execute(
            select(EconomicEvent).where(
                EconomicEvent.recurrence_key == "cpi_2027_02"
            )
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].event_date == date(2027, 2, 12)  # updated in place
    assert rows[0].source == EventSource.FRED.value  # source flipped to live
