#!/usr/bin/env python3
"""
Seed macro economic events for the calendar.

Creates events for:
- FOMC meetings (2025-2026)
- CPI releases (monthly)
- NFP/Jobs reports (monthly)
- GDP releases (quarterly)
- PCE releases (monthly, BEA "Personal Income and Outlays")
- PPI releases (monthly, 2026 only -- see the PPI block below)
- Retail sales releases (monthly, 2026 only -- Census "Advance Monthly Sales
  for Retail and Food Services"; see the retail-sales block below)

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

Every run also retires SEED-source rows the current spec lists no longer
define (``EconomicEventService.retire_orphaned_macro_events``), so a shrunk or
corrected spec list self-cleans instead of leaving stale rows behind forever
-- ``--clear`` remains as a manual full-wipe escape hatch, but normal re-seeds
no longer need it.

Calendar accuracy audit (2026-07-21, issue 015 -- docs/issues/015-calendar-accuracy-audit.md):
FOMC and GDP were re-derived from their primary calendars (federalreserve.gov,
bea.gov) and corrected -- see the source/citation block above each list below.
CPI and NFP were NOT re-derived in that first pass: bls.gov was unreachable
from that pass's fetch tooling (HTTP 403 on every path tried).

CPI/NFP follow-up (2026-07-23, issue 015 continued): bls.gov is still
403-blocked from every egress tried (including residential IPs), so CPI and
NFP were re-derived instead from Wayback Machine captures of BLS's own
schedule pages (web.archive.org mirrors of bls.gov/schedule/news_release/
cpi.htm and .../empsit.htm) -- see the source/citation blocks above
``CPI_DATES_2025`` and ``NFP_DATES_2025`` below for the exact capture URLs.

PCE/PPI follow-up (2026-08-14, issue #265): PCE was the one series the two
passes above never re-derived, so it still carried pre-audit guesses AND had
no 2026 table at all -- ``seed_statistical_specs`` gated it behind
``if year == 2025:``, silently producing no PCE row for any month of 2026.
PPI was absent from this pipeline entirely. Both are now derived from primary
sources (bea.gov directly; bls.gov via Wayback, still 403 live) and the
year-gate is replaced by the declared ``_MONTHLY_SERIES`` coverage table, whose
gaps every run prints.

Retail-sales follow-up (2026-08-14, issue #265 continued): the third gap #265
recorded and left out of scope. ``EventType.RETAIL_SALES`` was already in the
enum, the macro-type lists and the frontend's calendar wiring -- only this
pipeline had never heard of it. Its dates come from Census's own release
calendar, fetched DIRECTLY (census.gov is reachable from this egress, unlike
bls.gov and fred.stlouisfed.org) -- see the block above
``RETAIL_SALES_DATES_2026``. Like PPI it has no FRED release id here, so it is
seeded on both the live and fallback paths via ``seed_only_specs``.

Usage:
    cd backend
    python -m scripts.seed_macro_events
    python -m scripts.seed_macro_events --year 2026
    python -m scripts.seed_macro_events --clear    # Clear auto-seeded events first
    python -m scripts.seed_macro_events --no-live   # Force the seed lists (skip FRED)
"""

import argparse
import asyncio
import re
from datetime import date, time

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.models.economic_event import EconomicEvent, EventSource, EventType
from app.services.data_providers.fred import (
    RELEASE_IDS,
    FredCalendarProvider,
    MacroEventSpec,
    macro_recurrence_key,
    monthly_release_ordinals,
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
FOMC_DATES_2025: list[tuple[date, date]] = [
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

FOMC_DATES_2026: list[tuple[date, date]] = [
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
# Source: https://www.bls.gov/schedule/news_release/cpi.htm -- unreachable
# live (HTTP 403 from every egress tried, including residential IPs), so
# re-derived (2026-07-23, issue 015 continued) from Wayback Machine mirrors
# of that page:
#   https://web.archive.org/web/20250111210513/https://www.bls.gov/schedule/news_release/cpi.htm
#     (captured 2025-01-11 -- original pre-shutdown 2025 schedule, Dec-2024
#     through Nov-2025 data; cross-checked byte-identical against the
#     2025-05-20, 2025-07-19 and 2025-09-10 captures below)
#   https://web.archive.org/web/20250520035747/https://www.bls.gov/schedule/news_release/cpi.htm
#   https://web.archive.org/web/20250719181414/https://www.bls.gov/schedule/news_release/cpi.htm
#   https://web.archive.org/web/20250910071545/https://www.bls.gov/schedule/news_release/cpi.htm
#   https://web.archive.org/web/20251025032156/https://www.bls.gov/schedule/news_release/cpi.htm
#     (captured 2025-10-25, one day after the Sep-2025 release -- confirms
#     the shutdown-driven COLA release Oct 24, 2025, replacing the
#     originally-planned Oct 15, 2025)
#   https://web.archive.org/web/20251121185534/https://www.bls.gov/schedule/news_release/cpi.htm
#     (captured 2025-11-21 -- first stable post-shutdown capture: confirms
#     the Oct-2025 CPI was canceled outright -- no "October 2025" row -- and
#     the Nov-2025 CPI moved to Dec 18, 2025)
#   https://web.archive.org/web/20260213183647/https://www.bls.gov/schedule/news_release/cpi.htm
#     (captured 2026-02-13, release day -- confirms the Jan-2026 CPI's
#     second-lapse-driven move from Feb 11 to Feb 13, 2026)
#   https://web.archive.org/web/20260702222336/https://www.bls.gov/schedule/news_release/cpi.htm
#     (captured 2026-07-02 -- most recent full-year-coverage capture,
#     confirms the full Dec-2025-through-Nov-2026-data schedule below;
#     cross-checked unchanged against the 2026-05-01 capture)
#
# 2025 corrected: three routine one-day-off guesses plus the Oct-Nov 2025
# shutdown's disruption of the last three releases.
#   - Jun-2025 data: Jul 11 -> Jul 15, 2025 (routine guess, not shutdown-related)
#   - Jul-2025 data: Aug 13 -> Aug 12, 2025 (routine guess)
#   - Aug-2025 data: Sep 10 -> Sep 11, 2025 (routine guess)
#   - Sep-2025 data: Oct 15 -> Oct 24, 2025 (shutdown: special COLA-driven release)
#   - Oct-2025 data: CANCELED outright (was guessed Nov 13, 2025) -- omitted
#     below entirely, mirroring the GDP shutdown-cancellation pattern (see #220)
#   - Nov-2025 data: Dec 10 -> Dec 18, 2025 (shutdown-delayed)
#
# 2026 corrected: the Dec-2025/Jan-2026 releases (tail of the shutdown
# disruption, including a second lapse) plus four routine one-day-off guesses.
#   - Dec-2025 data: Jan 14 -> Jan 13, 2026
#   - Jan-2026 data: Feb 11 -> Feb 13, 2026 (second lapse)
#   - Mar-2026 data: Apr 14 -> Apr 10, 2026 (routine guess)
#   - Aug-2026 data: Sep 15 -> Sep 11, 2026 (routine guess)
#   - Sep-2026 data: Oct 13 -> Oct 14, 2026 (routine guess)
#   - Oct-2026 data: Nov 12 -> Nov 10, 2026 (routine guess)
#   - Nov-2026 data: Dec 9 -> Dec 10, 2026 (routine guess)
# ============================================================================

CPI_DATES_2025: list[date] = [
    date(2025, 1, 15),   # Dec 2024 data
    date(2025, 2, 12),   # Jan 2025 data
    date(2025, 3, 12),   # Feb
    date(2025, 4, 10),   # Mar
    date(2025, 5, 13),   # Apr
    date(2025, 6, 11),   # May
    date(2025, 7, 15),   # Jun -- CORRECTED (was Jul 11)
    date(2025, 8, 12),   # Jul -- CORRECTED (was Aug 13)
    date(2025, 9, 11),   # Aug -- CORRECTED (was Sep 10)
    date(2025, 10, 24),  # Sep -- CORRECTED (was Oct 15; shutdown COLA release)
    # Oct 2025 CPI was CANCELED outright by the Oct-Nov 2025 shutdown -- no
    # entry (was guessed Nov 13, 2025). See source block above.
    date(2025, 12, 18),  # Nov -- CORRECTED (was Dec 10; shutdown-delayed)
]

CPI_DATES_2026: list[date] = [
    date(2026, 1, 13),   # Dec 2025 data -- CORRECTED (was Jan 14)
    date(2026, 2, 13),   # Jan 2026 data -- CORRECTED (was Feb 11; second lapse)
    date(2026, 3, 11),   # Feb
    date(2026, 4, 10),   # Mar -- CORRECTED (was Apr 14)
    date(2026, 5, 12),   # Apr
    date(2026, 6, 10),   # May
    date(2026, 7, 14),   # Jun
    date(2026, 8, 12),   # Jul
    date(2026, 9, 11),   # Aug -- CORRECTED (was Sep 15)
    date(2026, 10, 14),  # Sep -- CORRECTED (was Oct 13)
    date(2026, 11, 10),  # Oct -- CORRECTED (was Nov 12)
    date(2026, 12, 10),  # Nov -- CORRECTED (was Dec 9)
]


# ============================================================================
# NFP (Non-Farm Payrolls) / Jobs Report (first Friday of month)
# Source: https://www.bls.gov/schedule/news_release/empsit.htm -- unreachable
# live (same HTTP 403 blocker as CPI above), so re-derived (2026-07-23,
# issue 015 continued) from Wayback Machine mirrors of that page:
#   https://web.archive.org/web/20250719172653/https://www.bls.gov/schedule/news_release/empsit.htm
#     (captured 2025-07-19 -- original pre-shutdown 2025 schedule, Dec-2024
#     through Nov-2025 data; cross-checked byte-identical against the
#     2025-09-10 and 2025-10-06 captures below)
#   https://web.archive.org/web/20250910073017/https://www.bls.gov/schedule/news_release/empsit.htm
#   https://web.archive.org/web/20251006223843/https://www.bls.gov/schedule/news_release/empsit.htm
#   https://web.archive.org/web/20251121185540/https://www.bls.gov/schedule/news_release/empsit.htm
#     (captured 2025-11-21 -- first stable post-shutdown capture: Sep-2025
#     jobs report delayed to Nov 20, 2025; Oct-2025 report never separately
#     published -- no "October 2025" row; Nov-2025 report moved to Dec 16, 2025)
#   https://web.archive.org/web/20260213183650/https://www.bls.gov/schedule/news_release/empsit.htm
#     (captured 2026-02-13 -- confirms the Jan-2026 jobs report's move from
#     the originally-planned Feb 6 to Feb 11, 2026, a second-lapse effect
#     matching the CPI Feb 11->13 shift above)
#   https://web.archive.org/web/20260702082019/https://www.bls.gov/schedule/news_release/empsit.htm
#     (captured 2026-07-02 -- most recent full-year-coverage capture,
#     confirms the full Dec-2025-through-Nov-2026-data schedule below;
#     cross-checked unchanged against the 2026-05-01 capture)
#
# 2025 corrected: only the last three releases moved, all shutdown-driven --
# every other 2025 date below was already correct.
#   - Sep-2025 data: Oct 3 -> Nov 20, 2025 (shutdown-delayed)
#   - Oct-2025 data: never separately published (partial data folded into
#     the next report) -- omitted below entirely (was guessed Nov 7, 2025),
#     mirroring the GDP/CPI shutdown-cancellation pattern (see #220 / above)
#   - Nov-2025 data: Dec 5 -> Dec 16, 2025 (shutdown-delayed)
#
# 2026 corrected: only the Jan-2026 release moved (tail of the shutdown
# disruption, a second lapse) -- every other 2026 date below was already
# correct.
#   - Jan-2026 data: Feb 6 -> Feb 11, 2026 (second lapse)
# ============================================================================

NFP_DATES_2025: list[date] = [
    date(2025, 1, 10),   # Dec 2024 data
    date(2025, 2, 7),    # Jan
    date(2025, 3, 7),    # Feb
    date(2025, 4, 4),    # Mar
    date(2025, 5, 2),    # Apr
    date(2025, 6, 6),    # May
    date(2025, 7, 3),    # Jun
    date(2025, 8, 1),    # Jul
    date(2025, 9, 5),    # Aug
    date(2025, 11, 20),  # Sep -- CORRECTED (was Oct 3; shutdown-delayed)
    # Oct 2025 jobs report was never separately published (partial data
    # folded into the next report) by the Oct-Nov 2025 shutdown -- no entry
    # (was guessed Nov 7, 2025). See source block above.
    date(2025, 12, 16),  # Nov -- CORRECTED (was Dec 5; shutdown-delayed)
]

NFP_DATES_2026: list[date] = [
    date(2026, 1, 9),    # Dec 2025 data
    date(2026, 2, 11),   # Jan 2026 data -- CORRECTED (was Feb 6; second lapse)
    date(2026, 3, 6),    # Feb
    date(2026, 4, 3),    # Mar
    date(2026, 5, 8),    # Apr
    date(2026, 6, 5),    # May
    date(2026, 7, 2),    # Jun
    date(2026, 8, 7),    # Jul
    date(2026, 9, 4),    # Aug
    date(2026, 10, 2),   # Sep
    date(2026, 11, 6),   # Oct
    date(2026, 12, 4),   # Nov
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
# STRUCTURAL COLLISION -- MECHANICS FIXED, AND NOW ENCODED. The corrected
# Q4-2025 Third estimate (Apr 9, 2026) and Q1-2026's Advance estimate (Apr 30,
# 2026, itself corrected by one day from a guessed Apr 29) both land in April
# 2026. The recurrence key disambiguates same-month GDP prints by estimate
# ordinal ("gdp_2026_04_third" vs "gdp_2026_04_advance"), so both are safe to
# encode.
#
# The mechanics landed first and the two calendar entries were deliberately
# held back as a separate data decision. That decision was taken on 2026-08-14
# (Andrew elected): both are RESTORED below, re-verified the same day against
# bea.gov's own full-2026 schedule table, which lists them as
#   "April 9 ... GDP (Third Estimate), Industries, Corporate Profits, State
#    GDP, and State Personal Income, 4th Quarter and Year 2025"
#   "April 30 ... GDP (Advance Estimate), 1st Quarter 2026"
# Individual press pages for each, recorded when they were first derived:
#   Apr 9, 2026 Q4-2025 Third -- https://www.bea.gov/news/2026/gdp-third-estimate-industries-corporate-profits-state-gdp-and-state-personal-income-4th
#   Apr 30, 2026 Q1-2026 Advance -- https://www.bea.gov/news/2026/gdp-advance-estimate-1st-quarter-2026
# April 2026 is now the only month in either year carrying two GDP entries.
# ============================================================================

GDP_DATES_2025: list[tuple[date, str]] = [
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

GDP_DATES_2026: list[tuple[date, str]] = [
    (date(2026, 1, 22), "Q3 2025 Updated Estimate"),  # NEW -- replaces the would-be Dec 19, 2025 Third estimate
    (date(2026, 2, 20), "Q4 2025 Advance"),   # CORRECTED -- moved from Jan 29, 2026 (shutdown)
    (date(2026, 3, 13), "Q4 2025 Second"),    # CORRECTED -- moved from Feb 26, 2026 (shutdown)
    (date(2026, 4, 9), "Q4 2025 Third"),      # RESTORED 2026-08-14 -- moved from Mar 27 (shutdown)
    (date(2026, 4, 30), "Q1 2026 Advance"),   # RESTORED 2026-08-14 -- April's second real release
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
# PCE (Personal Consumption Expenditures) — Fed's preferred inflation measure.
# BEA publishes it in the "Personal Income and Outlays" release.
# Source: https://www.bea.gov/news/schedule -- full-2025 and full-2026 tabs
# (https://www.bea.gov/news/schedule/full-2025 and .../full, which list every
# release of the year including ones already published, not just upcoming).
# Retrieved: 2026-08-14 (issue #265). bea.gov is reachable directly, so unlike
# CPI/NFP these needed no Wayback archaeology.
#
# 2025 corrected (issue #265): the 2025 list was never re-derived in the
# 2026-07-21 issue-015 audit -- that pass covered FOMC/GDP, and the 2026-07-23
# follow-up covered CPI/NFP. So PCE alone still carried the pre-audit guesses,
# and the Oct-Nov 2025 shutdown broke its last three exactly the way it broke
# CPI's, NFP's and GDP's:
#   - Sep-2025 data: Oct 31 -> Dec 5, 2025 (shutdown-delayed, released 10:00 AM)
#   - Oct-2025 + Nov-2025 data: NOT released separately in 2025 at all. BEA
#     COMBINED them into a single Jan 22, 2026 release (see PCE_DATES_2026),
#     so the guessed Nov 26 and Dec 23, 2025 entries are removed here rather
#     than moved. This mirrors the CPI/NFP/GDP cancellation pattern.
#
# 2026 (NEW -- the issue's headline gap): PCE_DATES_2026 never existed, so
# ``seed_statistical_specs`` gated PCE behind ``if year == 2025:`` and the
# 2026 calendar silently carried no PCE rows for the whole year. The early
# 2026 dates are shutdown-shifted and are NOT derivable from the normal
# end-of-following-month cadence:
#   - Oct+Nov 2025 data: combined catch-up release, Jan 22, 2026 (10:00 AM)
#   - Dec-2025 data: Feb 20, 2026 (co-released with Q4-2025 GDP Advance)
#   - Jan-2026 data: Mar 13, 2026, moved from Feb 26 --
#     https://www.bea.gov/index.php/news/blog/2026-01-15/economic-release-schedule-updates-gdp-personal-income-and-outlays
#   - Feb-2026 data: Apr 9, 2026, moved from Mar 27 (same BEA notice)
# From Mar-2026 data (Apr 30) onward the cadence is back to normal and each
# PCE release is co-released with that month's GDP estimate -- every date from
# Apr 30 on matches GDP_DATES_2026 exactly, which is a useful cross-check.
#
# SAME-MONTH COLLISION (resolved, not deferred): April 2026 carries TWO real
# releases -- Apr 9 (Feb-2026 data) and Apr 30 (Mar-2026 data). Under the
# month-bucketed recurrence key those collide. Unlike the GDP April-2026
# collision (still deliberately unencoded -- see the GDP block above), these
# are resolved here via ``monthly_release_ordinals``, so both real releases
# are seeded. See that helper in fred.py for why positional ordinals.
# ============================================================================

PCE_DATES_2025: list[date] = [
    date(2025, 1, 31),   # Dec 2024 data
    date(2025, 2, 28),   # Jan 2025 data
    date(2025, 3, 28),   # Feb
    date(2025, 4, 30),   # Mar (released 10:00 AM)
    date(2025, 5, 30),   # Apr
    date(2025, 6, 27),   # May
    date(2025, 7, 31),   # Jun
    date(2025, 8, 29),   # Jul
    date(2025, 9, 26),   # Aug
    date(2025, 12, 5),   # Sep -- CORRECTED (was Oct 31; shutdown-delayed)
    # Oct-2025 and Nov-2025 data were NOT released separately in 2025 -- BEA
    # combined them into the Jan 22, 2026 release in PCE_DATES_2026. The old
    # guesses (Nov 26 and Dec 23, 2025) are removed, not moved. See above.
]

PCE_DATES_2026: list[date] = [
    date(2026, 1, 22),   # Oct + Nov 2025 data, combined catch-up (10:00 AM)
    date(2026, 2, 20),   # Dec 2025 data
    date(2026, 3, 13),   # Jan 2026 -- moved from Feb 26 (BEA notice)
    date(2026, 4, 9),    # Feb -- moved from Mar 27; April collision 1 of 2
    date(2026, 4, 30),   # Mar -- back on cadence; April collision 2 of 2
    date(2026, 5, 28),   # Apr
    date(2026, 6, 25),   # May
    date(2026, 7, 30),   # Jun
    date(2026, 8, 26),   # Jul
    date(2026, 9, 30),   # Aug
    date(2026, 10, 29),  # Sep
    date(2026, 11, 25),  # Oct
    date(2026, 12, 23),  # Nov
]


# ============================================================================
# PPI (Producer Price Index) — wholesale/input inflation, often a leading
# indicator for CPI.
# Source: https://www.bls.gov/schedule/news_release/ppi.htm -- unreachable
# live (the same HTTP 403 blocker as CPI/NFP above, still in force from this
# egress on 2026-08-14), so derived from Wayback Machine mirrors:
#   https://web.archive.org/web/20260731041441/https://www.bls.gov/schedule/news_release/ppi.htm
#     (captured 2026-07-31 -- the most recent capture, full-year coverage)
#   https://web.archive.org/web/20260213183648/https://www.bls.gov/schedule/news_release/ppi.htm
#     (captured 2026-02-13 -- earliest 2026 capture)
# The two captures agree on every row below, and the Wayback CDX digest is
# byte-identical across the 2026-03-19, 05-01, 05-15, 06-12 and 07-31
# captures, so the schedule has been stable since mid-March 2026.
#
# NEW in issue #265: PPI had no date table, no meta, no seeder call and no
# entry in MACRO_SEED_EVENT_TYPES -- ``EventType.PPI`` existed in the enum and
# was accepted by ADD_CALENDAR_EVENT, but the seeding pipeline had never heard
# of it, so the calendar carried no PPI row in any month of 2026.
#
# SAME-MONTH COLLISION (resolved): January 2026 carries TWO real releases --
# Jan 14 (Nov-2025 data) and Jan 30 (Dec-2025 data), the shutdown catch-up.
# Handled by ``monthly_release_ordinals``, same as PCE's April above.
#
# Deliberately 2026-only: there is no PPI_DATES_2025. Back-filling 2025 would
# need its own shutdown-era derivation (the Oct-2025 release was canceled
# outright, matching CPI) for events that are entirely in the past and gate no
# decision. The gap is declared in ``_MONTHLY_SERIES`` and printed by every
# seeder run rather than hidden behind a year check -- which is exactly the
# failure mode this issue was filed about.
# ============================================================================

PPI_DATES_2026: list[date] = [
    date(2026, 1, 14),   # Nov 2025 data -- January collision 1 of 2
    date(2026, 1, 30),   # Dec 2025 data -- January collision 2 of 2
    date(2026, 2, 27),   # Jan 2026 data
    date(2026, 3, 18),   # Feb
    date(2026, 4, 14),   # Mar
    date(2026, 5, 13),   # Apr
    date(2026, 6, 11),   # May
    date(2026, 7, 15),   # Jun
    date(2026, 8, 13),   # Jul
    date(2026, 9, 10),   # Aug
    date(2026, 10, 15),  # Sep
    date(2026, 11, 13),  # Oct
    date(2026, 12, 15),  # Nov
]


# ============================================================================
# Retail Sales Release Schedule (Census "Advance Monthly Sales for Retail and
# Food Services", MARTS)
# Source: https://www.census.gov/economic-indicators/calendar-listview.html
# Retrieved: 2026-08-14 (fetched DIRECTLY -- census.gov is reachable from this
# egress, unlike bls.gov and fred.stlouisfed.org, which are both still
# HTTP-403-blocked and forced the Wayback derivations used for CPI/NFP/PPI).
# Read twice by different means (rendered page + raw HTML parse) and both
# agree on all 13 rows. Census's own machine-readable codes on each row pin
# both halves independently: the release stamp (A202601140830 = 2026-01-14
# 08:30) and the reference period (A202511 = Nov 2025 data).
#
# NEW in issue #265: retail sales was the third gap that issue recorded and
# the one it deliberately left out of scope. ``EventType.RETAIL_SALES``
# existed in the enum, in ``MACRO_EVENT_TYPES``, in ``is_macro_event``, and
# the frontend already had its label/color/filter wiring -- only this seeding
# pipeline had never heard of it, so the calendar carried no retail-sales row
# in any month of 2026.
#
# Not a FRED release here: unlike CPI/NFP/GDP/PCE this is a Census indicator,
# and it has no entry in ``RELEASE_IDS`` (fred.stlouisfed.org is 403-blocked
# from this egress, so its release id could not be verified, and guessing one
# would risk pulling another release's dates into a calendar that gates trade
# decisions). It is therefore seeded on BOTH paths via ``seed_only_specs``,
# exactly like PPI.
#
# SAME-MONTH COLLISION (resolved): April 2026 carries TWO real releases --
# Apr 1 (Feb-2026 data) and Apr 21 (Mar-2026 data), the shutdown catch-up
# finally closing. Handled by ``monthly_release_ordinals``, same as PCE's
# April and PPI's January. The cadence is back to normal from May onward
# (May 14 for Apr data).
#
# Deliberately 2026-only: there is no RETAIL_SALES_DATES_2025. The Census
# calendar above publishes 2026 rows ONLY -- no 2025 release date appears on
# it at all -- so a 2025 table would need its own separate (and shutdown-era)
# derivation for events that are entirely in the past and gate no decision.
# The gap is declared in ``_MONTHLY_SERIES`` and printed by every seeder run
# rather than hidden behind a year check.
# ============================================================================

RETAIL_SALES_DATES_2026: list[date] = [
    date(2026, 1, 14),   # Nov 2025 data
    date(2026, 2, 10),   # Dec 2025 data
    date(2026, 3, 6),    # Jan 2026
    date(2026, 4, 1),    # Feb -- April collision 1 of 2
    date(2026, 4, 21),   # Mar -- April collision 2 of 2
    date(2026, 5, 14),   # Apr
    date(2026, 6, 17),   # May
    date(2026, 7, 16),   # Jun
    date(2026, 8, 14),   # Jul
    date(2026, 9, 16),   # Aug
    date(2026, 10, 15),  # Sep
    date(2026, 11, 17),  # Oct
    date(2026, 12, 16),  # Nov
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
_PPI_META = dict(
    title="PPI Report",
    description=(
        "Producer Price Index release. Wholesale/input inflation — often "
        "leads CPI at the consumer level."
    ),
    importance="medium",
    event_time=time(8, 30),
)
_RETAIL_SALES_META = dict(
    title="Retail Sales",
    description=(
        "Census Advance Monthly Sales for Retail and Food Services. The "
        "first read on consumer spending for the month."
    ),
    importance="medium",
    event_time=time(8, 30),
)


# Every monthly statistical series this script hand-maintains, and which years
# it actually has dates for. A year absent from a series' dict is a DECLARED
# gap: ``series_coverage`` reports it and every seeder run prints it.
#
# This table replaces a bare ``if year == 2025:`` around PCE, which is how PCE
# came to produce nothing at all for 2026 for a year without anyone noticing
# (issue #265). A missing year is now data, printed on every run — not
# control flow buried in a function.
_MONTHLY_SERIES: list[tuple[EventType, dict[int, list[date]], dict]] = [
    (EventType.CPI, {2025: CPI_DATES_2025, 2026: CPI_DATES_2026}, _CPI_META),
    (EventType.NFP, {2025: NFP_DATES_2025, 2026: NFP_DATES_2026}, _NFP_META),
    (EventType.PCE, {2025: PCE_DATES_2025, 2026: PCE_DATES_2026}, _PCE_META),
    # 2025 deliberately absent — see the PPI block comment above.
    (EventType.PPI, {2026: PPI_DATES_2026}, _PPI_META),
    # 2025 deliberately absent — see the retail-sales block comment above.
    (
        EventType.RETAIL_SALES,
        {2026: RETAIL_SALES_DATES_2026},
        _RETAIL_SALES_META,
    ),
]


def _fomc_specs(year: int) -> list[MacroEventSpec]:
    """FOMC meeting specs (always seeded — not a FRED release)."""
    dates = FOMC_DATES_2025 if year == 2025 else FOMC_DATES_2026
    specs: list[MacroEventSpec] = []
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
    event_type: EventType, dates: list[date], meta: dict
) -> list[MacroEventSpec]:
    """Build specs for a monthly release from a flat date list.

    Ordinals come from the shared ``monthly_release_ordinals`` helper so a
    month carrying two real releases (PPI's Jan 2026, PCE's Apr 2026) keys
    both instead of silently collapsing them onto one row — and so these keys
    stay identical to the ones the live FRED path computes for the same
    releases.
    """
    ordinals = monthly_release_ordinals(dates)
    return [
        MacroEventSpec(
            event_type=event_type.value,
            event_date=d,
            recurrence_key=macro_recurrence_key(
                event_type, d, ordinal=ordinals[d]
            ),
            **meta,
        )
        for d in dates
    ]


# Ordered longest/most-specific first so "Initial Estimate" / "Updated
# Estimate" (the shutdown-relabeled variants) are matched before a looser
# "Third" / "Second" substring inside them could apply instead.
_GDP_ORDINAL_TOKENS: list[tuple[str, str]] = [
    ("initial estimate", "initial_estimate"),
    ("updated estimate", "updated_estimate"),
    ("advance", "advance"),
    ("second", "second"),
    ("third", "third"),
]


def _gdp_ordinal(label: str) -> str:
    """Derive the recurrence-key ordinal token from a GDP seed-list label.

    The seed list's labels ("Q4 2024 Advance", "Q3 2025 Initial Estimate", ...)
    are the ground truth for which BEA estimate a date is for -- unlike the
    live FRED feed (see fred.gdp_estimate_ordinal), which only gets bare
    dates and has to guess.
    """
    lowered = label.lower()
    for token, slug in _GDP_ORDINAL_TOKENS:
        if token in lowered:
            return slug
    # Defensive fallback for an unrecognized label: never silently collapse
    # it onto another entry's key -- slugify the whole label so it stays
    # distinct (surfaces as an odd-looking but non-colliding key, not a
    # silent overwrite of a different release).
    return re.sub(r"[^a-z0-9]+", "_", lowered.strip()).strip("_") or "unknown"


def _is_advance_equivalent(label: str) -> bool:
    """True for labels that should get "high" importance the way a normal
    Advance estimate does.

    Government-shutdown-affected releases get relabeled -- e.g. the Q3-2025
    cycle's canceled Advance + Second merged into a single Dec 23, 2025
    "Initial Estimate" release (see the GDP_DATES_2025/2026 block comment
    above) -- and that relabeled release is the Advance-equivalent for
    importance-tagging purposes even though the substring "Advance" no
    longer appears in its label.
    """
    return "Advance" in label or "Initial Estimate" in label


def _gdp_specs(year: int) -> list[MacroEventSpec]:
    """GDP specs — month+ordinal-keyed (one row per BEA estimate), self-healing."""
    dates = GDP_DATES_2025 if year == 2025 else GDP_DATES_2026
    return [
        MacroEventSpec(
            event_type=EventType.GDP.value,
            event_date=d,
            recurrence_key=macro_recurrence_key(
                EventType.GDP, d, ordinal=_gdp_ordinal(label)
            ),
            title=f"GDP {label}",
            description="Gross Domestic Product report. Measures total economic output.",
            importance="high" if _is_advance_equivalent(label) else "medium",
            event_time=time(8, 30),
        )
        for d, label in dates
    ]


def seed_statistical_specs(year: int) -> list[MacroEventSpec]:
    """Hand-maintained CPI/NFP/GDP/PCE/PPI/retail-sales specs — the fallback
    when FRED is off."""
    specs: list[MacroEventSpec] = []
    for event_type, dates_by_year, meta in _MONTHLY_SERIES:
        specs += _monthly_specs(event_type, dates_by_year.get(year, []), meta)
    specs += _gdp_specs(year)
    return specs


def seed_only_specs(year: int) -> list[MacroEventSpec]:
    """Specs for the series the live FRED feed does NOT cover.

    ``resolve_macro_specs`` swaps the WHOLE statistical batch over to FRED
    when a key is configured. Any series FRED doesn't return would therefore
    vanish from the calendar the moment ``FRED_API_KEY`` is set — PPI and
    retail sales are the two today, because their FRED release ids could not
    be verified from this egress (fred.stlouisfed.org is 403-blocked here,
    same as bls.gov) and guessing an id would risk pulling some other
    release's dates into a calendar that gates trade decisions. So these are
    always seeded alongside the live feed.

    Membership is derived from ``RELEASE_IDS``, so adding a series to the live
    feed empties this automatically rather than leaving a duplicate behind.
    """
    specs: list[MacroEventSpec] = []
    for event_type, dates_by_year, meta in _MONTHLY_SERIES:
        if event_type in RELEASE_IDS:
            continue
        specs += _monthly_specs(event_type, dates_by_year.get(year, []), meta)
    return specs


def series_coverage(year: int) -> tuple[list[str], list[str]]:
    """``(covered, declared_gaps)`` event-type values for ``year``.

    Printed by every seeding run so a series producing nothing is visible in
    the output instead of being silently absent — the failure mode of issue
    #265, where PCE was gated to 2025 by an ``if`` and the 2026 calendar
    carried no PCE row for a year without anyone noticing.
    """
    covered: list[str] = []
    gaps: list[str] = []
    for event_type, dates_by_year, _meta in _MONTHLY_SERIES:
        target = covered if dates_by_year.get(year) else gaps
        target.append(event_type.value)
    return covered, gaps


# ============================================================================
# Orphan retirement -- current spec universe + retirement pass
#
# A shrunk or changed spec list (an entry removed/corrected, a year retired)
# used to leave the corresponding old row behind in the DB forever -- the
# only escape hatch was `--clear`, which wipes ALL macro data, not just the
# orphans. This section computes "what SHOULD exist right now" and the
# seeding entrypoint below uses it to retire exactly the SEED-source rows
# that have fallen out of it, so a normal re-seed self-cleans.
# ============================================================================

# Every year this script currently has hand-maintained lists for. Orphan
# retirement always evaluates against the FULL union across these years, NOT
# just whichever --year this invocation is seeding -- a single-year run must
# never treat the OTHER year's still-valid rows as orphaned just because this
# run didn't happen to touch them.
SEED_SPEC_YEARS: tuple[int, ...] = (2025, 2026)

# The event types the hand-maintained seed lists cover. Orphan retirement is
# scoped to exactly these -- a SEED-source row of some unrelated event type
# must never be swept up just because this pipeline's key universe doesn't
# include it. (scripts/seed_demo_data.py, a separate demo-environment
# pipeline against its own database, also tags rows EventSource.SEED with an
# entirely different GDP key scheme -- this scoping is what keeps this
# pipeline's retirement pass from ever being able to reach those rows even if
# it were ever pointed at the same database.)
MACRO_SEED_EVENT_TYPES: list[str] = [
    EventType.FOMC.value,
    EventType.CPI.value,
    EventType.NFP.value,
    EventType.GDP.value,
    EventType.PCE.value,
    EventType.PPI.value,
    EventType.RETAIL_SALES.value,
]


def current_seed_keys() -> set:
    """The full universe of recurrence_keys the hand-maintained seed lists
    currently define, across every supported year -- the orphan-retirement
    pass's "what should still exist" reference set."""
    keys: set = set()
    for seed_year in SEED_SPEC_YEARS:
        keys.update(spec.recurrence_key for spec in _fomc_specs(seed_year))
        keys.update(spec.recurrence_key for spec in seed_statistical_specs(seed_year))
    return keys


# ============================================================================
# Live-or-seed resolution + orchestration
# ============================================================================


async def resolve_macro_specs(
    provider: FredCalendarProvider, year: int, use_live: bool = True
) -> list[tuple[list[MacroEventSpec], str]]:
    """Decide the source for each event group and build its specs.

    Returns ``[(specs, source), ...]`` batches:
      * FOMC is always seeded.
      * CPI/NFP/GDP/PCE come from the live FRED feed when configured and it
        returns data; otherwise they gracefully fall back to the seed lists.
      * Series FRED doesn't cover (PPI today) are ALWAYS seeded — including on
        the live path, where the FRED batch replaces the statistical seed
        batch wholesale and would otherwise drop them. See ``seed_only_specs``.
    """
    batches: list[tuple[list[MacroEventSpec], str]] = [
        (_fomc_specs(year), EventSource.SEED.value)
    ]

    live_specs: list[MacroEventSpec] = []
    if use_live and provider.is_configured:
        live_specs = await provider.get_macro_events(year)

    if live_specs:
        batches.append((live_specs, EventSource.FRED.value))
        uncovered = seed_only_specs(year)
        if uncovered:
            batches.append((uncovered, EventSource.SEED.value))
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
    """Main seeding function: resolve source, upsert through the dedup path,
    then retire SEED-source rows the current spec lists no longer define."""
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

        # Per-type counts + declared gaps. A series that produced nothing is
        # printed here rather than silently missing -- issue #265's actual
        # failure mode was a year-gate nobody could see from the output.
        counts: dict[str, int] = {}
        for specs, _source in batches:
            for spec in specs:
                counts[spec.event_type] = counts.get(spec.event_type, 0) + 1
        print("  Seeded per type: " + ", ".join(
            f"{event_type}={counts.get(event_type, 0)}"
            for event_type in MACRO_SEED_EVENT_TYPES
        ))
        _covered, gaps = series_coverage(year)
        if gaps:
            print(f"  No hand-maintained {year} dates on file for: "
                  f"{', '.join(gaps)} (declared gap, not a failure)")

        # Orphan retirement (mechanics fix): see the module comment above
        # SEED_SPEC_YEARS. Scoped to SEED-source rows of the event types this
        # pipeline manages, across every supported year -- never just `year`,
        # and never a FRED-sourced or manual row. IMPORTANT ordering note: if
        # a prior GDP recurrence-key format is still live in the DB (i.e. the
        # 20260723_001 migration hasn't been applied yet), this pass would
        # see those rows' old-format keys as "not in the current (new-format)
        # spec" and delete real GDP history instead of leaving it for the
        # migration to re-key. That migration runs as a standalone Alembic
        # step at deploy time, strictly before this script is ever invoked
        # again (see PR body) -- this pass must never be reachable before it.
        retired = await service.retire_orphaned_macro_events(
            current_seed_keys(), MACRO_SEED_EVENT_TYPES
        )
        if retired:
            print(f"  Retired {retired} orphaned SEED-source event(s) no "
                  f"longer present in the current spec lists")


async def _seed_all(clear: bool = False, use_live: bool = True) -> None:
    """Seed both 2025 and 2026 within a SINGLE event loop.

    Kept as one coroutine (awaited under one ``asyncio.run()``) on purpose.
    The module-level async engine in ``app/db/session.py`` pools an asyncpg
    connection bound to the loop it is first used on. Driving 2025 and 2026
    under two *separate* ``asyncio.run()`` calls puts the second seed on a
    fresh loop, and the pooled connection -- still attached to loop 1 --
    raises ``RuntimeError: ... got Future ... attached to a different loop``.
    One loop for both years avoids that entirely (same bug class as
    docs/issues/012's Redis half), without disposing/recreating the engine
    between years.

    ``clear`` is honored only for the 2025 pass; 2026 never clears, so a
    ``--all --clear`` run doesn't wipe the rows the 2025 pass just wrote.
    """
    await seed_macro_events(2025, clear, use_live)
    await seed_macro_events(2026, False, use_live)  # Don't clear twice


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
        help=(
            "Clear ALL existing auto-seeded events first (manual escape hatch; "
            "normal re-seeds now self-clean orphans automatically, see "
            "retire_orphaned_macro_events)"
        ),
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
        asyncio.run(_seed_all(args.clear, use_live))
    else:
        asyncio.run(seed_macro_events(args.year, args.clear, use_live))


if __name__ == "__main__":
    main()
