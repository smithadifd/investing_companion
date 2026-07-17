#!/usr/bin/env python3
"""
Seed macro economic events for the calendar.

Creates events for:
- FOMC meetings (2025-2026)
- CPI releases (monthly)
- NFP/Jobs reports (monthly)
- GDP releases (quarterly)
- Other major economic indicators

Data source
-----------
When ``FRED_API_KEY`` is configured, the volatile monthly/quarterly statistical
releases (CPI/NFP/GDP/PCE) are pulled **live** from the FRED release calendar so
they stay self-healing and never run dry (issue 015). When the key is absent —
or a FRED fetch fails — this script falls back to the hand-maintained date lists
below so the calendar always gets seeded. FOMC meeting dates are not a FRED
release (the Fed publishes them a year ahead on its own calendar), so they are
always taken from the seed lists here.

Either way, every event flows through the single ``economic_events``
recurrence-key dedup path (``EconomicEventService.sync_macro_events``): the live
feed never bypasses it, and a re-run updates a moved date in place instead of
duplicating it.

Usage:
    cd backend
    python -m scripts.seed_macro_events
    python -m scripts.seed_macro_events --year 2026
    python -m scripts.seed_macro_events --clear    # Clear auto-seeded events first
    python -m scripts.seed_macro_events --no-live   # Force the seed lists (skip FRED)
"""

import argparse
import asyncio
from datetime import date, time
from typing import List, Tuple

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.models.economic_event import EconomicEvent, EventSource, EventType
from app.services.data_providers.fred import (
    FredCalendarProvider,
    MacroEventSpec,
    macro_recurrence_key,
)
from app.services.economic_event import EconomicEventService


# ============================================================================
# FOMC Meeting Schedule
# Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# ============================================================================

# FOMC meetings are typically 2-day events (Tue-Wed or Wed-Thu)
# Statement released at 2:00 PM ET on the second day
FOMC_DATES_2025: List[Tuple[date, date]] = [
    (date(2025, 1, 28), date(2025, 1, 29)),   # Jan 28-29
    (date(2025, 3, 18), date(2025, 3, 19)),   # Mar 18-19 (SEP*)
    (date(2025, 5, 6), date(2025, 5, 7)),     # May 6-7
    (date(2025, 6, 17), date(2025, 6, 18)),   # Jun 17-18 (SEP*)
    (date(2025, 7, 29), date(2025, 7, 30)),   # Jul 29-30
    (date(2025, 9, 16), date(2025, 9, 17)),   # Sep 16-17 (SEP*)
    (date(2025, 11, 4), date(2025, 11, 5)),   # Nov 4-5
    (date(2025, 12, 16), date(2025, 12, 17)), # Dec 16-17 (SEP*)
]
# * = Summary of Economic Projections meeting

FOMC_DATES_2026: List[Tuple[date, date]] = [
    # Tentative - typically released late 2025
    (date(2026, 1, 27), date(2026, 1, 28)),
    (date(2026, 3, 17), date(2026, 3, 18)),
    (date(2026, 5, 5), date(2026, 5, 6)),
    (date(2026, 6, 16), date(2026, 6, 17)),
    (date(2026, 7, 28), date(2026, 7, 29)),
    (date(2026, 9, 15), date(2026, 9, 16)),
    (date(2026, 11, 3), date(2026, 11, 4)),
    (date(2026, 12, 15), date(2026, 12, 16)),
]


# ============================================================================
# CPI Release Schedule (usually second week of month)
# Source: https://www.bls.gov/schedule/news_release/cpi.htm
# ============================================================================

CPI_DATES_2025: List[date] = [
    date(2025, 1, 15),   # Dec 2024 data
    date(2025, 2, 12),   # Jan 2025 data
    date(2025, 3, 12),   # Feb
    date(2025, 4, 10),   # Mar
    date(2025, 5, 13),   # Apr
    date(2025, 6, 11),   # May
    date(2025, 7, 11),   # Jun
    date(2025, 8, 13),   # Jul
    date(2025, 9, 10),   # Aug
    date(2025, 10, 15),  # Sep
    date(2025, 11, 13),  # Oct
    date(2025, 12, 10),  # Nov
]

CPI_DATES_2026: List[date] = [
    date(2026, 1, 14),
    date(2026, 2, 11),
    date(2026, 3, 11),
    date(2026, 4, 14),
    date(2026, 5, 12),
    date(2026, 6, 10),
    date(2026, 7, 14),
    date(2026, 8, 12),
    date(2026, 9, 15),
    date(2026, 10, 13),
    date(2026, 11, 12),
    date(2026, 12, 9),
]


# ============================================================================
# NFP (Non-Farm Payrolls) / Jobs Report (first Friday of month)
# Source: https://www.bls.gov/schedule/news_release/empsit.htm
# ============================================================================

NFP_DATES_2025: List[date] = [
    date(2025, 1, 10),   # Dec 2024 data
    date(2025, 2, 7),    # Jan
    date(2025, 3, 7),    # Feb
    date(2025, 4, 4),    # Mar
    date(2025, 5, 2),    # Apr
    date(2025, 6, 6),    # May
    date(2025, 7, 3),    # Jun
    date(2025, 8, 1),    # Jul
    date(2025, 9, 5),    # Aug
    date(2025, 10, 3),   # Sep
    date(2025, 11, 7),   # Oct
    date(2025, 12, 5),   # Nov
]

NFP_DATES_2026: List[date] = [
    date(2026, 1, 9),
    date(2026, 2, 6),
    date(2026, 3, 6),
    date(2026, 4, 3),
    date(2026, 5, 8),
    date(2026, 6, 5),
    date(2026, 7, 2),
    date(2026, 8, 7),
    date(2026, 9, 4),
    date(2026, 10, 2),
    date(2026, 11, 6),
    date(2026, 12, 4),
]


# ============================================================================
# GDP Release Schedule (quarterly, ~1 month after quarter end)
# Three releases: Advance, Second, Third
# ============================================================================

GDP_DATES_2025: List[Tuple[date, str]] = [
    (date(2025, 1, 30), "Q4 2024 Advance"),
    (date(2025, 2, 27), "Q4 2024 Second"),
    (date(2025, 3, 27), "Q4 2024 Third"),
    (date(2025, 4, 30), "Q1 2025 Advance"),
    (date(2025, 5, 29), "Q1 2025 Second"),
    (date(2025, 6, 26), "Q1 2025 Third"),
    (date(2025, 7, 30), "Q2 2025 Advance"),
    (date(2025, 8, 28), "Q2 2025 Second"),
    (date(2025, 9, 25), "Q2 2025 Third"),
    (date(2025, 10, 30), "Q3 2025 Advance"),
    (date(2025, 11, 26), "Q3 2025 Second"),
    (date(2025, 12, 23), "Q3 2025 Third"),
]

GDP_DATES_2026: List[Tuple[date, str]] = [
    (date(2026, 1, 29), "Q4 2025 Advance"),
    (date(2026, 2, 26), "Q4 2025 Second"),
    (date(2026, 3, 26), "Q4 2025 Third"),
    (date(2026, 4, 29), "Q1 2026 Advance"),
    (date(2026, 5, 28), "Q1 2026 Second"),
    (date(2026, 6, 25), "Q1 2026 Third"),
    (date(2026, 7, 30), "Q2 2026 Advance"),
    (date(2026, 8, 27), "Q2 2026 Second"),
    (date(2026, 9, 24), "Q2 2026 Third"),
    (date(2026, 10, 29), "Q3 2026 Advance"),
    (date(2026, 11, 25), "Q3 2026 Second"),
    (date(2026, 12, 22), "Q3 2026 Third"),
]


# ============================================================================
# PCE (Personal Consumption Expenditures) - Fed's preferred inflation measure
# Usually released ~1 week after CPI
# ============================================================================

PCE_DATES_2025: List[date] = [
    date(2025, 1, 31),
    date(2025, 2, 28),
    date(2025, 3, 28),
    date(2025, 4, 30),
    date(2025, 5, 30),
    date(2025, 6, 27),
    date(2025, 7, 31),
    date(2025, 8, 29),
    date(2025, 9, 26),
    date(2025, 10, 31),
    date(2025, 11, 26),
    date(2025, 12, 23),
]


# ============================================================================
# Seed-list -> MacroEventSpec builders (the fallback source)
#
# These turn the hand-maintained date lists above into the same source-agnostic
# ``MacroEventSpec`` the live FRED provider emits, so both flow through one dedup
# path. ``recurrence_key`` comes from the shared ``macro_recurrence_key`` helper,
# guaranteeing live and seeded events share the exact dedup identity.
# ============================================================================

_CPI_META = dict(
    title="CPI Report",
    description="Consumer Price Index release. Key inflation indicator tracked by markets and the Fed.",
    importance="high",
    event_time=time(8, 30),
)
_NFP_META = dict(
    title="Non-Farm Payrolls",
    description="Monthly employment situation report. Includes job growth, unemployment rate, and wage data.",
    importance="high",
    event_time=time(8, 30),
)
_PCE_META = dict(
    title="PCE Price Index",
    description="Personal Consumption Expenditures price index. The Fed's preferred inflation measure.",
    importance="medium",
    event_time=time(8, 30),
)


def _fomc_specs(year: int) -> List[MacroEventSpec]:
    """FOMC meeting specs (always seeded — not a FRED release)."""
    dates = FOMC_DATES_2025 if year == 2025 else FOMC_DATES_2026
    specs: List[MacroEventSpec] = []
    for _day1, day2 in dates:
        # The statement lands on day 2.
        specs.append(
            MacroEventSpec(
                event_type=EventType.FOMC.value,
                event_date=day2,
                recurrence_key=macro_recurrence_key(EventType.FOMC, day2),
                title="FOMC Rate Decision",
                description=(
                    "Federal Reserve FOMC meeting concludes. Interest rate "
                    "decision and statement released at 2:00 PM ET."
                ),
                importance="high",
                event_time=time(14, 0),  # 2:00 PM ET
            )
        )
    return specs


def _monthly_specs(
    event_type: EventType, dates: List[date], meta: dict
) -> List[MacroEventSpec]:
    """Build specs for a monthly release from a flat date list."""
    return [
        MacroEventSpec(
            event_type=event_type.value,
            event_date=d,
            recurrence_key=macro_recurrence_key(event_type, d),
            **meta,
        )
        for d in dates
    ]


def _gdp_specs(year: int) -> List[MacroEventSpec]:
    """GDP specs — day-keyed (multiple quarterly vintages can share a month)."""
    dates = GDP_DATES_2025 if year == 2025 else GDP_DATES_2026
    return [
        MacroEventSpec(
            event_type=EventType.GDP.value,
            event_date=d,
            recurrence_key=macro_recurrence_key(EventType.GDP, d),
            title=f"GDP {label}",
            description="Gross Domestic Product report. Measures total economic output.",
            importance="high" if "Advance" in label else "medium",
            event_time=time(8, 30),
        )
        for d, label in dates
    ]


def seed_statistical_specs(year: int) -> List[MacroEventSpec]:
    """Hand-maintained CPI/NFP/GDP/PCE specs — the fallback when FRED is off."""
    specs: List[MacroEventSpec] = []
    specs += _monthly_specs(
        EventType.CPI, CPI_DATES_2025 if year == 2025 else CPI_DATES_2026, _CPI_META
    )
    specs += _monthly_specs(
        EventType.NFP, NFP_DATES_2025 if year == 2025 else NFP_DATES_2026, _NFP_META
    )
    specs += _gdp_specs(year)
    if year == 2025:  # Only 2025 PCE dates are hand-maintained.
        specs += _monthly_specs(EventType.PCE, PCE_DATES_2025, _PCE_META)
    return specs


# ============================================================================
# Live-or-seed resolution + orchestration
# ============================================================================


async def resolve_macro_specs(
    provider: FredCalendarProvider, year: int, use_live: bool = True
) -> List[Tuple[List[MacroEventSpec], str]]:
    """Decide the source for each event group and build its specs.

    Returns ``[(specs, source), ...]`` batches:
      * FOMC is always seeded.
      * CPI/NFP/GDP/PCE come from the live FRED feed when configured and it
        returns data; otherwise they gracefully fall back to the seed lists.
    """
    batches: List[Tuple[List[MacroEventSpec], str]] = [
        (_fomc_specs(year), EventSource.SEED.value)
    ]

    live_specs: List[MacroEventSpec] = []
    if use_live and provider.is_configured:
        live_specs = await provider.get_macro_events(year)

    if live_specs:
        batches.append((live_specs, EventSource.FRED.value))
    else:
        batches.append((seed_statistical_specs(year), EventSource.SEED.value))

    return batches


async def clear_seeded_events(db: AsyncSession) -> int:
    """Clear auto-seeded macro events (seed + live FRED).

    Preserves Yahoo-sourced equity events and user custom (manual) events.
    """
    result = await db.execute(
        delete(EconomicEvent).where(
            EconomicEvent.source.in_(
                [EventSource.SEED.value, EventSource.FRED.value]
            )
        )
    )
    await db.commit()
    return result.rowcount


async def seed_macro_events(
    year: int = 2025, clear: bool = False, use_live: bool = True
) -> None:
    """Main seeding function: resolve source, upsert through the dedup path."""
    provider = FredCalendarProvider()

    async with AsyncSessionLocal() as db:
        service = EconomicEventService(db)

        if clear:
            deleted = await clear_seeded_events(db)
            print(f"Cleared {deleted} auto-seeded events")

        batches = await resolve_macro_specs(provider, year, use_live)
        live_used = any(src == EventSource.FRED.value for _, src in batches)
        source_label = "FRED live feed" if live_used else "hand-maintained seed lists"
        print(f"\nSeeding macro events for {year} (statistical source: {source_label})...")

        total_created = 0
        total_seen = 0
        for specs, source in batches:
            res = await service.sync_macro_events(specs, source=source)
            total_created += res["created"]
            total_seen += res["created"] + res["updated"]

        print(f"  Processed {total_seen} events ({total_created} created, "
              f"{total_seen - total_created} updated in place)")


def main():
    parser = argparse.ArgumentParser(description="Seed macro economic events")
    parser.add_argument(
        "--year",
        type=int,
        default=2025,
        choices=[2025, 2026],
        help="Year to seed (default: 2025)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing auto-seeded events first",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Seed both 2025 and 2026",
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        help="Force the hand-maintained seed lists (skip the FRED live feed)",
    )

    args = parser.parse_args()
    use_live = not args.no_live

    if args.all:
        asyncio.run(seed_macro_events(2025, args.clear, use_live))
        asyncio.run(seed_macro_events(2026, False, use_live))  # Don't clear twice
    else:
        asyncio.run(seed_macro_events(args.year, args.clear, use_live))


if __name__ == "__main__":
    main()
