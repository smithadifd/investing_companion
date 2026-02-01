#!/usr/bin/env python3
"""
Seed macro economic events for the calendar.

Creates events for:
- FOMC meetings (2025-2026)
- CPI releases (monthly)
- NFP/Jobs reports (monthly)
- GDP releases (quarterly)
- Other major economic indicators

Usage:
    cd backend
    python -m scripts.seed_macro_events
    python -m scripts.seed_macro_events --year 2026
    python -m scripts.seed_macro_events --clear  # Clear existing seeded events first
"""

import argparse
import asyncio
from datetime import date, time
from typing import List, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.models.economic_event import EconomicEvent, EventSource, EventType


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
# Seeding Functions
# ============================================================================


async def create_fomc_events(db: AsyncSession, year: int) -> int:
    """Create FOMC meeting events."""
    dates = FOMC_DATES_2025 if year == 2025 else FOMC_DATES_2026
    count = 0

    for day1, day2 in dates:
        # Create event for day 2 (when statement is released)
        recurrence_key = f"fomc_{day2.year}_{day2.month:02d}"

        existing = await db.execute(
            select(EconomicEvent).where(EconomicEvent.recurrence_key == recurrence_key)
        )
        if existing.scalar_one_or_none():
            continue

        event = EconomicEvent(
            event_type=EventType.FOMC.value,
            event_date=day2,
            event_time=time(14, 0),  # 2:00 PM ET
            all_day=False,
            title=f"FOMC Rate Decision",
            description=f"Federal Reserve FOMC meeting concludes. Interest rate decision and statement released at 2:00 PM ET.",
            importance="high",
            source=EventSource.SEED.value,
            is_confirmed=True,
            recurrence_key=recurrence_key,
        )
        db.add(event)
        count += 1

    await db.commit()
    return count


async def create_cpi_events(db: AsyncSession, year: int) -> int:
    """Create CPI release events."""
    dates = CPI_DATES_2025 if year == 2025 else CPI_DATES_2026
    count = 0

    for event_date in dates:
        recurrence_key = f"cpi_{event_date.year}_{event_date.month:02d}"

        existing = await db.execute(
            select(EconomicEvent).where(EconomicEvent.recurrence_key == recurrence_key)
        )
        if existing.scalar_one_or_none():
            continue

        event = EconomicEvent(
            event_type=EventType.CPI.value,
            event_date=event_date,
            event_time=time(8, 30),  # 8:30 AM ET
            all_day=False,
            title="CPI Report",
            description="Consumer Price Index release. Key inflation indicator tracked by markets and the Fed.",
            importance="high",
            source=EventSource.SEED.value,
            is_confirmed=True,
            recurrence_key=recurrence_key,
        )
        db.add(event)
        count += 1

    await db.commit()
    return count


async def create_nfp_events(db: AsyncSession, year: int) -> int:
    """Create NFP (Jobs Report) events."""
    dates = NFP_DATES_2025 if year == 2025 else NFP_DATES_2026
    count = 0

    for event_date in dates:
        recurrence_key = f"nfp_{event_date.year}_{event_date.month:02d}"

        existing = await db.execute(
            select(EconomicEvent).where(EconomicEvent.recurrence_key == recurrence_key)
        )
        if existing.scalar_one_or_none():
            continue

        event = EconomicEvent(
            event_type=EventType.NFP.value,
            event_date=event_date,
            event_time=time(8, 30),  # 8:30 AM ET
            all_day=False,
            title="Non-Farm Payrolls",
            description="Monthly employment situation report. Includes job growth, unemployment rate, and wage data.",
            importance="high",
            source=EventSource.SEED.value,
            is_confirmed=True,
            recurrence_key=recurrence_key,
        )
        db.add(event)
        count += 1

    await db.commit()
    return count


async def create_gdp_events(db: AsyncSession, year: int) -> int:
    """Create GDP release events."""
    dates = GDP_DATES_2025 if year == 2025 else GDP_DATES_2026
    count = 0

    for event_date, label in dates:
        recurrence_key = f"gdp_{event_date.year}_{event_date.month:02d}_{event_date.day:02d}"

        existing = await db.execute(
            select(EconomicEvent).where(EconomicEvent.recurrence_key == recurrence_key)
        )
        if existing.scalar_one_or_none():
            continue

        event = EconomicEvent(
            event_type=EventType.GDP.value,
            event_date=event_date,
            event_time=time(8, 30),  # 8:30 AM ET
            all_day=False,
            title=f"GDP {label}",
            description="Gross Domestic Product report. Measures total economic output.",
            importance="high" if "Advance" in label else "medium",
            source=EventSource.SEED.value,
            is_confirmed=True,
            recurrence_key=recurrence_key,
        )
        db.add(event)
        count += 1

    await db.commit()
    return count


async def create_pce_events(db: AsyncSession, year: int) -> int:
    """Create PCE inflation events."""
    if year != 2025:
        return 0  # Only have 2025 data for now

    dates = PCE_DATES_2025
    count = 0

    for event_date in dates:
        recurrence_key = f"pce_{event_date.year}_{event_date.month:02d}"

        existing = await db.execute(
            select(EconomicEvent).where(EconomicEvent.recurrence_key == recurrence_key)
        )
        if existing.scalar_one_or_none():
            continue

        event = EconomicEvent(
            event_type=EventType.PCE.value,
            event_date=event_date,
            event_time=time(8, 30),  # 8:30 AM ET
            all_day=False,
            title="PCE Price Index",
            description="Personal Consumption Expenditures price index. The Fed's preferred inflation measure.",
            importance="medium",
            source=EventSource.SEED.value,
            is_confirmed=True,
            recurrence_key=recurrence_key,
        )
        db.add(event)
        count += 1

    await db.commit()
    return count


async def clear_seeded_events(db: AsyncSession) -> int:
    """Clear all seeded events (preserves Yahoo-sourced and custom events)."""
    result = await db.execute(
        delete(EconomicEvent).where(EconomicEvent.source == EventSource.SEED.value)
    )
    await db.commit()
    return result.rowcount


async def seed_macro_events(year: int = 2025, clear: bool = False) -> None:
    """Main seeding function."""
    async with AsyncSessionLocal() as db:
        if clear:
            deleted = await clear_seeded_events(db)
            print(f"Cleared {deleted} seeded events")

        print(f"\nSeeding macro events for {year}...")

        fomc_count = await create_fomc_events(db, year)
        print(f"  FOMC meetings: {fomc_count}")

        cpi_count = await create_cpi_events(db, year)
        print(f"  CPI releases: {cpi_count}")

        nfp_count = await create_nfp_events(db, year)
        print(f"  NFP reports: {nfp_count}")

        gdp_count = await create_gdp_events(db, year)
        print(f"  GDP releases: {gdp_count}")

        pce_count = await create_pce_events(db, year)
        print(f"  PCE releases: {pce_count}")

        total = fomc_count + cpi_count + nfp_count + gdp_count + pce_count
        print(f"\nTotal events created: {total}")


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
        help="Clear existing seeded events first",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Seed both 2025 and 2026",
    )

    args = parser.parse_args()

    if args.all:
        asyncio.run(seed_macro_events(2025, args.clear))
        asyncio.run(seed_macro_events(2026, False))  # Don't clear twice
    else:
        asyncio.run(seed_macro_events(args.year, args.clear))


if __name__ == "__main__":
    main()
