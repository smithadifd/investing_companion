# Issue 015: Calendar Accuracy Audit (Seeded Macro Dates)

**Status:** Open
**Created:** 2026-04-19
**Priority:** Medium
**Affects:** Calendar, Morning Pulse, EOD Wrap

## Summary

Seeded macro economic event dates (FOMC, CPI, NFP, GDP) in `backend/scripts/seed_macro_events.py` are hardcoded lists. A recent CPI entry appeared to be on the wrong date, so the whole calendar needs to be audited against authoritative sources.

## Scope

Verify every date in `CPI_DATES_2026`, `NFP_DATES_2026`, `FOMC_DATES_2026`, and any GDP dates against:

- **CPI**: https://www.bls.gov/schedule/news_release/cpi.htm
- **NFP/Employment Situation**: https://www.bls.gov/schedule/news_release/empsit.htm
- **FOMC**: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- **GDP**: https://www.bea.gov/news/schedule

Also audit 2025 dates — events that already fired may have propagated to notifications with wrong dates.

## Suggested Approach

1. Cross-check each hardcoded list against the official release schedule pages.
2. For any mismatch, correct the date and note the prior/expected date in a comment.
3. Consider replacing the hardcoded lists with a scheduled fetch from an authoritative source (FRED, investpy, or scraping BLS/Fed schedule pages) to keep the calendar self-healing.
4. Re-seed the DB after corrections: `python -m scripts.seed_macro_events --clear --year 2026`.

## Context

Reported 2026-04-19 after a CPI entry appeared on the wrong date in the morning pulse / tomorrow's events summary. Calendar accuracy affects morning pulse, EOD wrap (tomorrow's events section), and the Events page.
