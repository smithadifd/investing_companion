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

Calendar accuracy audit (2026-07-21, issue 015 -- docs/issues/015-calendar-accuracy-audit.md):
FOMC and GDP were re-derived from their primary calendars (federalreserve.gov,
bea.gov) and corrected -- see the source/citation block above each list below.
CPI and NFP were NOT re-derived this pass: bls.gov was unreachable from this
pass's fetch tooling (HTTP 403 on every path tried) -- see the block comments
above ``CPI_DATES_2025``/``NFP_DATES_2025`` for the follow-up.

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
# Retrieved: 2026-07-21 (fetched directly from the Fed's own calendar page;
# cross-checked against FOMC minutes/press-release URLs — e.g.
# fomcminutes20250917.htm confirms Sep 16-17, 2025; monetary20250822a.htm
# confirms the Aug 22, 2025 item below is real but is NOT a rate-decision
# meeting).
#
# 2025 corrected: the last two meetings were guessed one week late.
#   - Nov 4-5, 2025 -> Oct 28-29, 2025 (real meeting 7 days earlier)
#   - Dec 16-17, 2025 -> Dec 9-10, 2025 (real meeting 7 days earlier, SEP)
# Excluded on purpose: Aug 22, 2025 is a "notation vote" approving the Fed's
# Statement on Longer-Run Goals and Monetary Policy Strategy — an
# administrative vote, not a 2-day meeting with a 2pm ET rate statement, so
# it doesn't fit this list's (day1, day2) rate-decision shape and isn't one
# of the Fed's 8 regularly scheduled meetings.
#
# 2026 corrected (previously marked "Tentative"; now the Fed's confirmed
# published calendar): three meetings were guessed exactly 7 days late.
#   - May 5-6, 2026 -> Apr 28-29, 2026
#   - Nov 3-4, 2026 -> Oct 27-28, 2026
#   - Dec 15-16, 2026 -> Dec 8-9, 2026 (SEP)
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
    (date(2025, 10, 28), date(2025, 10, 29)), # Oct 28-29 -- CORRECTED (was Nov 4-5)
    (date(2025, 12, 9), date(2025, 12, 10)),  # Dec 9-10 (SEP*) -- CORRECTED (was Dec 16-17)
]
# * = Summary of Economic Projections meeting

FOMC_DATES_2026: List[Tuple[date, date]] = [
    # Fed's confirmed published 2026 calendar (see source note above).
    (date(2026, 1, 27), date(2026, 1, 28)),   # Jan 27-28
    (date(2026, 3, 17), date(2026, 3, 18)),   # Mar 17-18 (SEP*)
    (date(2026, 4, 28), date(2026, 4, 29)),   # Apr 28-29 -- CORRECTED (was May 5-6)
    (date(2026, 6, 16), date(2026, 6, 17)),   # Jun 16-17 (SEP*)
    (date(2026, 7, 28), date(2026, 7, 29)),   # Jul 28-29
    (date(2026, 9, 15), date(2026, 9, 16)),   # Sep 15-16 (SEP*)
    (date(2026, 10, 27), date(2026, 10, 28)), # Oct 27-28 -- CORRECTED (was Nov 3-4)
    (date(2026, 12, 8), date(2026, 12, 9)),   # Dec 8-9 (SEP*) -- CORRECTED (was Dec 15-16)
]


# ============================================================================
# CPI Release Schedule (usually second week of month)
# Source: https://www.bls.gov/schedule/news_release/cpi.htm
#
# NOT RE-DERIVED in the 2026-07-21 pass (issue 015 audit): every bls.gov path
# tried (schedule/news_release/cpi.htm, bls/2025-lapse-revised-release-dates.htm,
# schedule/2026/home.htm, schedule/news_release/current_year.asp, cpi/,
# news.release/cpi.htm, download.bls.gov, apps.bls.gov) returned HTTP 403 or
# failed DNS resolution for this pass's fetch tooling — the primary source is
# unreachable, so per this fix's decision authority these dates are LEFT AS-IS
# rather than corrected from a secondary source. Known independently
# corroborated (news-secondary, NOT used to change code here) via the Oct-Nov
# 2025 shutdown: the Sep-2025 CPI (normally ~Oct 15) had a special COLA-driven
# release Oct 24, 2025; the Oct-2025 CPI was canceled outright; Nov-2025 CPI
# released Dec 18, 2025; Dec-2025 CPI released Jan 13, 2026; a SECOND
# lapse pushed Jan-2026 CPI from Feb 11 to Feb 13, 2026. Follow-up: re-run this
# derivation once bls.gov is reachable (e.g. an authenticated/browser fetch).
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
#
# NOT RE-DERIVED in the 2026-07-21 pass — same bls.gov unreachable blocker as
# CPI above (see that block comment). Known independently corroborated
# (news-secondary, NOT used to change code here): the Sep-2025 jobs report
# (normally ~Oct 3) was delayed to Nov 20, 2025; the Oct-2025 report was never
# separately published (partial data folded into the next report); Nov-2025
# released Dec 16, 2025. Follow-up: re-run once bls.gov is reachable.
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
# Three releases: Advance, Second, Third -- except where the 2025 shutdown
# collapsed the cycle (see below).
# Source: https://www.bea.gov/news/schedule (full-2025 / full-2026 tabs, plus
# individual embargoed press releases). Retrieved: 2026-07-21.
#
# The Oct-Nov 2025 government shutdown collapsed BEA's Q3-2025 cycle: the
# Advance estimate (originally Oct 30, 2025) and the Second estimate
# (originally Nov 26, 2025) were both CANCELED ("sufficient source data will
# not be available in time") and merged into one "Initial Estimate" released
# Dec 23, 2025 --
# https://www.bea.gov/news/2025/gross-domestic-product-3rd-quarter-2025-initial-estimate-and-corporate-profits.
# The would-be Third estimate (originally Dec 19, 2025) became an "Updated
# Estimate" released Jan 22, 2026, BEA 26-04 --
# https://www.bea.gov/sites/default/files/2026-01/gdp3q25-updated.pdf.
# The Q4-2025 cycle was pushed in turn: Advance Jan 29 -> Feb 20, 2026;
# Second Feb 26 -> Mar 13, 2026; Third Mar 27 -> Apr 9, 2026 --
# https://www.bea.gov/index.php/news/blog/2026-01-15/economic-release-schedule-updates-gdp-personal-income-and-outlays,
# https://www.bea.gov/news/2026/gdp-third-estimate-industries-corporate-profits-state-gdp-and-state-personal-income-4th.
# By Q1-2026 the cycle is back on its original cadence: Second and Third
# landed on their originally-scheduled May 28 / Jun 25, 2026 dates, confirmed
# directly against https://www.bea.gov/news/2026/gdp-second-estimate-and-corporate-profits-1st-quarter-2026
# and https://www.bea.gov/news/2026/gdp-third-estimate-industries-corporate-profits-state-gdp-and-state-personal-income-1st.
#
# STRUCTURAL COLLISION (reported, not resolved here -- see PR description):
# the corrected Q4-2025 Third estimate (Apr 9, 2026) and Q1-2026's Advance
# estimate (Apr 30, 2026, itself corrected by one day from a guessed Apr 29)
# both land in April 2026. ``macro_recurrence_key`` buckets GDP by
# release-month (fred.py), i.e. one GDP row per calendar month, so encoding
# both would silently collide/overwrite in the DB upsert -- a mechanics
# change (finer-grained recurrence key) that is out of scope for this
# date-only fix. Neither date is added below; both citations are recorded
# here so a follow-up mechanics PR doesn't have to re-derive them:
#   Apr 9, 2026 Q4-2025 Third -- https://www.bea.gov/news/2026/gdp-third-estimate-industries-corporate-profits-state-gdp-and-state-personal-income-4th
#   Apr 30, 2026 Q1-2026 Advance -- https://www.bea.gov/news/2026/gdp-advance-estimate-1st-quarter-2026
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
    # Oct 30 "Q3 2025 Advance" and Nov 26 "Q3 2025 Second" were CANCELED by
    # the shutdown and merged into the single Dec 23 release below (see the
    # block comment above) -- no October or November GDP release occurred.
    (date(2025, 12, 23), "Q3 2025 Initial Estimate"),  # CORRECTED label (was "Q3 2025 Third"); date unchanged
]

GDP_DATES_2026: List[Tuple[date, str]] = [
    (date(2026, 1, 22), "Q3 2025 Updated Estimate"),  # NEW -- replaces the would-be Dec 19, 2025 Third estimate
    (date(2026, 2, 20), "Q4 2025 Advance"),   # CORRECTED -- moved from Jan 29, 2026 (shutdown)
    (date(2026, 3, 13), "Q4 2025 Second"),    # CORRECTED -- moved from Feb 26, 2026 (shutdown)
    # April 2026 intentionally has no entry: Apr 9 "Q4 2025 Third" and
    # Apr 30 "Q1 2026 Advance" both fall here -- a structural collision under
    # the month-bucketed recurrence key. See STRUCTURAL COLLISION note above.
    (date(2026, 5, 28), "Q1 2026 Second"),    # confirmed unchanged
    (date(2026, 6, 25), "Q1 2026 Third"),     # confirmed unchanged
    (date(2026, 7, 30), "Q2 2026 Advance"),   # confirmed unchanged
    (date(2026, 8, 26), "Q2 2026 Second"),    # CORRECTED (was Aug 27)
    (date(2026, 9, 30), "Q2 2026 Third"),     # CORRECTED (was Sep 24)
    (date(2026, 10, 29), "Q3 2026 Advance"),  # confirmed unchanged
    (date(2026, 11, 25), "Q3 2026 Second"),   # confirmed unchanged
    (date(2026, 12, 23), "Q3 2026 Third"),    # CORRECTED (was Dec 22)
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
    """GDP specs — month-keyed (one GDP print per calendar month), self-healing."""
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
