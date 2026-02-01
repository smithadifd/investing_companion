#!/usr/bin/env python3
"""
Production seed script for Investing Companion.

Seeds the database with:
1. Default ratios (common financial ratios for analysis)
2. Market indices (for market overview page)
3. Macro economic events (FOMC, CPI, NFP, GDP)

This script is idempotent - safe to run multiple times.

Usage:
    cd backend
    python -m scripts.seed_demo_data
    python -m scripts.seed_demo_data --all      # Seed everything
    python -m scripts.seed_demo_data --ratios   # Seed ratios only
    python -m scripts.seed_demo_data --events   # Seed macro events only
    python -m scripts.seed_demo_data --year 2026  # Specific year for events
"""

import argparse
import asyncio
from datetime import date, time
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.models.ratio import Ratio
from app.db.models.economic_event import EconomicEvent, EventSource, EventType


# ============================================================================
# Default Ratios
# ============================================================================

DEFAULT_RATIOS = [
    # Commodity ratios
    {
        "name": "Gold/Silver Ratio",
        "numerator_symbol": "GLD",
        "denominator_symbol": "SLV",
        "description": "Historical average around 60. Values above 80 may signal silver undervaluation, below 50 may signal overvaluation.",
        "category": "commodity",
        "is_system": True,
        "is_favorite": True,
    },
    {
        "name": "Copper/Gold Ratio",
        "numerator_symbol": "CPER",
        "denominator_symbol": "GLD",
        "description": "Economic bellwether - rising ratio suggests economic optimism, falling ratio suggests risk-off sentiment.",
        "category": "macro",
        "is_system": True,
        "is_favorite": False,
    },
    # Equity ratios
    {
        "name": "SPY/QQQ Ratio",
        "numerator_symbol": "SPY",
        "denominator_symbol": "QQQ",
        "description": "Broad market vs tech. Rising ratio = value/cyclicals outperforming, falling = tech leadership.",
        "category": "equity",
        "is_system": True,
        "is_favorite": True,
    },
    {
        "name": "Value/Growth Ratio",
        "numerator_symbol": "VTV",
        "denominator_symbol": "VUG",
        "description": "Factor rotation indicator. Rising ratio = value style outperforming growth.",
        "category": "equity",
        "is_system": True,
        "is_favorite": False,
    },
    {
        "name": "Small Cap/Large Cap",
        "numerator_symbol": "IWM",
        "denominator_symbol": "SPY",
        "description": "Risk appetite indicator. Rising ratio = small caps outperforming, often signals bullish sentiment.",
        "category": "equity",
        "is_system": True,
        "is_favorite": False,
    },
    # Macro ratios
    {
        "name": "TLT/IEF Ratio",
        "numerator_symbol": "TLT",
        "denominator_symbol": "IEF",
        "description": "Long vs intermediate Treasury bonds. Proxy for yield curve slope expectations.",
        "category": "macro",
        "is_system": True,
        "is_favorite": False,
    },
    {
        "name": "High Yield/Investment Grade",
        "numerator_symbol": "HYG",
        "denominator_symbol": "LQD",
        "description": "Credit risk appetite. Rising ratio = risk-on in credit markets.",
        "category": "macro",
        "is_system": True,
        "is_favorite": False,
    },
    # Sector ratios
    {
        "name": "Uranium/Energy",
        "numerator_symbol": "URA",
        "denominator_symbol": "XLE",
        "description": "Uranium vs traditional energy performance. Tracks nuclear energy thesis.",
        "category": "equity",
        "is_system": True,
        "is_favorite": False,
    },
    {
        "name": "Tech/Utilities",
        "numerator_symbol": "XLK",
        "denominator_symbol": "XLU",
        "description": "Risk appetite indicator. Tech vs defensive utilities.",
        "category": "equity",
        "is_system": True,
        "is_favorite": False,
    },
    # Crypto
    {
        "name": "Gold/Bitcoin",
        "numerator_symbol": "GLD",
        "denominator_symbol": "BITO",
        "description": "Traditional safe haven vs digital gold. Tracks relative preference.",
        "category": "crypto",
        "is_system": True,
        "is_favorite": False,
    },
]


# ============================================================================
# Macro Event Schedules
# ============================================================================

# FOMC meetings - statement released on day 2 at 2:00 PM ET
FOMC_DATES_2025 = [
    (date(2025, 1, 29), "January"),
    (date(2025, 3, 19), "March (SEP)"),
    (date(2025, 5, 7), "May"),
    (date(2025, 6, 18), "June (SEP)"),
    (date(2025, 7, 30), "July"),
    (date(2025, 9, 17), "September (SEP)"),
    (date(2025, 11, 5), "November"),
    (date(2025, 12, 17), "December (SEP)"),
]

FOMC_DATES_2026 = [
    (date(2026, 1, 28), "January"),
    (date(2026, 3, 18), "March (SEP)"),
    (date(2026, 5, 6), "May"),
    (date(2026, 6, 17), "June (SEP)"),
    (date(2026, 7, 29), "July"),
    (date(2026, 9, 16), "September (SEP)"),
    (date(2026, 11, 4), "November"),
    (date(2026, 12, 16), "December (SEP)"),
]

# CPI releases - typically second week of month at 8:30 AM ET
CPI_DATES_2025 = [
    date(2025, 1, 15), date(2025, 2, 12), date(2025, 3, 12),
    date(2025, 4, 10), date(2025, 5, 13), date(2025, 6, 11),
    date(2025, 7, 11), date(2025, 8, 13), date(2025, 9, 10),
    date(2025, 10, 15), date(2025, 11, 13), date(2025, 12, 10),
]

CPI_DATES_2026 = [
    date(2026, 1, 14), date(2026, 2, 11), date(2026, 3, 11),
    date(2026, 4, 14), date(2026, 5, 12), date(2026, 6, 10),
    date(2026, 7, 14), date(2026, 8, 12), date(2026, 9, 15),
    date(2026, 10, 13), date(2026, 11, 12), date(2026, 12, 9),
]

# NFP/Jobs report - first Friday of month at 8:30 AM ET
NFP_DATES_2025 = [
    date(2025, 1, 10), date(2025, 2, 7), date(2025, 3, 7),
    date(2025, 4, 4), date(2025, 5, 2), date(2025, 6, 6),
    date(2025, 7, 3), date(2025, 8, 1), date(2025, 9, 5),
    date(2025, 10, 3), date(2025, 11, 7), date(2025, 12, 5),
]

NFP_DATES_2026 = [
    date(2026, 1, 9), date(2026, 2, 6), date(2026, 3, 6),
    date(2026, 4, 3), date(2026, 5, 8), date(2026, 6, 5),
    date(2026, 7, 2), date(2026, 8, 7), date(2026, 9, 4),
    date(2026, 10, 2), date(2026, 11, 6), date(2026, 12, 4),
]

# GDP releases - quarterly
GDP_DATES_2025 = [
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

GDP_DATES_2026 = [
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
# Seeding Functions
# ============================================================================

async def seed_ratios(db: AsyncSession) -> int:
    """Seed default ratios. Skips existing ratios (by name)."""
    count = 0

    for ratio_data in DEFAULT_RATIOS:
        # Check if ratio already exists
        result = await db.execute(
            select(Ratio).where(Ratio.name == ratio_data["name"])
        )
        if result.scalar_one_or_none():
            continue

        ratio = Ratio(**ratio_data)
        db.add(ratio)
        count += 1

    await db.commit()
    return count


async def seed_fomc_events(db: AsyncSession, year: int) -> int:
    """Seed FOMC meeting events."""
    dates = FOMC_DATES_2025 if year == 2025 else FOMC_DATES_2026
    count = 0

    for event_date, label in dates:
        recurrence_key = f"fomc_{event_date.year}_{event_date.month:02d}"

        result = await db.execute(
            select(EconomicEvent).where(
                EconomicEvent.recurrence_key == recurrence_key
            )
        )
        if result.scalar_one_or_none():
            continue

        is_sep = "SEP" in label
        event = EconomicEvent(
            event_type=EventType.FOMC.value,
            event_date=event_date,
            event_time=time(14, 0),  # 2:00 PM ET
            all_day=False,
            title=f"FOMC Rate Decision",
            description=f"{label} meeting. Rate decision and statement at 2:00 PM ET." +
                        (" Includes Summary of Economic Projections." if is_sep else ""),
            importance="high",
            source=EventSource.SEED.value,
            is_confirmed=True,
            recurrence_key=recurrence_key,
        )
        db.add(event)
        count += 1

    await db.commit()
    return count


async def seed_cpi_events(db: AsyncSession, year: int) -> int:
    """Seed CPI release events."""
    dates = CPI_DATES_2025 if year == 2025 else CPI_DATES_2026
    count = 0

    for event_date in dates:
        recurrence_key = f"cpi_{event_date.year}_{event_date.month:02d}"

        result = await db.execute(
            select(EconomicEvent).where(
                EconomicEvent.recurrence_key == recurrence_key
            )
        )
        if result.scalar_one_or_none():
            continue

        event = EconomicEvent(
            event_type=EventType.CPI.value,
            event_date=event_date,
            event_time=time(8, 30),  # 8:30 AM ET
            all_day=False,
            title="CPI Report",
            description="Consumer Price Index release. Key inflation metric.",
            importance="high",
            source=EventSource.SEED.value,
            is_confirmed=True,
            recurrence_key=recurrence_key,
        )
        db.add(event)
        count += 1

    await db.commit()
    return count


async def seed_nfp_events(db: AsyncSession, year: int) -> int:
    """Seed NFP (Jobs Report) events."""
    dates = NFP_DATES_2025 if year == 2025 else NFP_DATES_2026
    count = 0

    for event_date in dates:
        recurrence_key = f"nfp_{event_date.year}_{event_date.month:02d}"

        result = await db.execute(
            select(EconomicEvent).where(
                EconomicEvent.recurrence_key == recurrence_key
            )
        )
        if result.scalar_one_or_none():
            continue

        event = EconomicEvent(
            event_type=EventType.NFP.value,
            event_date=event_date,
            event_time=time(8, 30),  # 8:30 AM ET
            all_day=False,
            title="Non-Farm Payrolls",
            description="Monthly employment report with jobs, unemployment, wages.",
            importance="high",
            source=EventSource.SEED.value,
            is_confirmed=True,
            recurrence_key=recurrence_key,
        )
        db.add(event)
        count += 1

    await db.commit()
    return count


async def seed_gdp_events(db: AsyncSession, year: int) -> int:
    """Seed GDP release events."""
    dates = GDP_DATES_2025 if year == 2025 else GDP_DATES_2026
    count = 0

    for event_date, label in dates:
        recurrence_key = f"gdp_{event_date.year}_{event_date.month:02d}_{event_date.day:02d}"

        result = await db.execute(
            select(EconomicEvent).where(
                EconomicEvent.recurrence_key == recurrence_key
            )
        )
        if result.scalar_one_or_none():
            continue

        event = EconomicEvent(
            event_type=EventType.GDP.value,
            event_date=event_date,
            event_time=time(8, 30),  # 8:30 AM ET
            all_day=False,
            title=f"GDP {label}",
            description="Gross Domestic Product report.",
            importance="high" if "Advance" in label else "medium",
            source=EventSource.SEED.value,
            is_confirmed=True,
            recurrence_key=recurrence_key,
        )
        db.add(event)
        count += 1

    await db.commit()
    return count


async def seed_events(db: AsyncSession, year: int) -> dict:
    """Seed all macro events for a year."""
    return {
        "fomc": await seed_fomc_events(db, year),
        "cpi": await seed_cpi_events(db, year),
        "nfp": await seed_nfp_events(db, year),
        "gdp": await seed_gdp_events(db, year),
    }


async def seed_all(years: List[int] = None) -> None:
    """Seed all production data."""
    if years is None:
        years = [2025, 2026]

    async with AsyncSessionLocal() as db:
        # Seed ratios
        ratio_count = await seed_ratios(db)
        print(f"Ratios seeded: {ratio_count}")

        # Seed events for each year
        for year in years:
            print(f"\nSeeding events for {year}:")
            counts = await seed_events(db, year)
            for event_type, count in counts.items():
                print(f"  {event_type.upper()}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description="Seed production data for Investing Companion"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Seed all data (default)"
    )
    parser.add_argument(
        "--ratios", action="store_true",
        help="Seed ratios only"
    )
    parser.add_argument(
        "--events", action="store_true",
        help="Seed macro events only"
    )
    parser.add_argument(
        "--year", type=int, choices=[2025, 2026],
        help="Specific year for events (default: both 2025 and 2026)"
    )

    args = parser.parse_args()

    # Default to all if no specific option given
    seed_ratios_flag = args.all or args.ratios or not (args.ratios or args.events)
    seed_events_flag = args.all or args.events or not (args.ratios or args.events)

    async def run():
        async with AsyncSessionLocal() as db:
            if seed_ratios_flag:
                count = await seed_ratios(db)
                print(f"Ratios seeded: {count}")

            if seed_events_flag:
                years = [args.year] if args.year else [2025, 2026]
                for year in years:
                    print(f"\nSeeding events for {year}:")
                    counts = await seed_events(db, year)
                    for event_type, count in counts.items():
                        print(f"  {event_type.upper()}: {count}")

    asyncio.run(run())
    print("\nSeeding complete!")


if __name__ == "__main__":
    main()
