"""Regression fixtures pinning the issue-015 calendar-accuracy corrections.

Network- and DB-free: exercises the raw hand-maintained date lists in
``scripts/seed_macro_events`` directly. Every expected dataset here sits next
to the official primary source that pins it so a future regression trips
against a cited receipt, not a guess.

Scope (see the block comments in seed_macro_events.py for the full
derivation):
  - FOMC 2025 + 2026: fully re-derived from federalreserve.gov (reachable),
    retrieved 2026-07-21.
  - GDP 2025 + 2026: fully re-derived from bea.gov (reachable), retrieved
    2026-07-21, including the Oct-Nov 2025 shutdown's cancellations/mergers
    and one reported (not resolved) structural collision in April 2026.
  - CPI / NFP 2025 + 2026: bls.gov itself is still unreachable (HTTP 403 from
    every egress tried, including residential IPs) as of the 2026-07-23
    follow-up, so these were re-derived from Wayback Machine captures of
    BLS's own schedule pages instead -- see the block comments above
    ``CPI_DATES_2025`` and ``NFP_DATES_2025`` in the script for the exact
    capture URLs.
"""

from datetime import date

from scripts.seed_macro_events import (
    CPI_DATES_2025,
    CPI_DATES_2026,
    FOMC_DATES_2025,
    FOMC_DATES_2026,
    GDP_DATES_2025,
    GDP_DATES_2026,
    MACRO_SEED_EVENT_TYPES,
    NFP_DATES_2025,
    NFP_DATES_2026,
    PCE_DATES_2025,
    PCE_DATES_2026,
    PPI_DATES_2026,
    _gdp_ordinal,
    _is_advance_equivalent,
    seed_only_specs,
    seed_statistical_specs,
    series_coverage,
)


class TestFomc2025Dates:
    """Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    (retrieved 2026-07-21). Cross-checked against
    fomcminutes20250917.htm (Sep 16-17) and monetary20250822a.htm (confirms
    the Aug 22 item is a notation vote, not a rate-decision meeting -- hence
    excluded from this 8-meeting list)."""

    def test_matches_fed_calendar_exactly(self):
        assert FOMC_DATES_2025 == [
            (date(2025, 1, 28), date(2025, 1, 29)),
            (date(2025, 3, 18), date(2025, 3, 19)),
            (date(2025, 5, 6), date(2025, 5, 7)),
            (date(2025, 6, 17), date(2025, 6, 18)),
            (date(2025, 7, 29), date(2025, 7, 30)),
            (date(2025, 9, 16), date(2025, 9, 17)),
            (date(2025, 10, 28), date(2025, 10, 29)),
            (date(2025, 12, 9), date(2025, 12, 10)),
        ]

    def test_known_wrong_examples_now_correct(self):
        """The #36 verifier's receipts: both meetings were guessed one week
        late in the pre-fix seed list."""
        assert (date(2025, 10, 28), date(2025, 10, 29)) in FOMC_DATES_2025
        assert (date(2025, 11, 4), date(2025, 11, 5)) not in FOMC_DATES_2025
        assert (date(2025, 12, 9), date(2025, 12, 10)) in FOMC_DATES_2025
        assert (date(2025, 12, 16), date(2025, 12, 17)) not in FOMC_DATES_2025


class TestFomc2026Dates:
    """Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    (retrieved 2026-07-21) -- the Fed's confirmed published 2026 calendar
    (was previously hand-guessed and marked "Tentative" in this file)."""

    def test_matches_fed_calendar_exactly(self):
        assert FOMC_DATES_2026 == [
            (date(2026, 1, 27), date(2026, 1, 28)),
            (date(2026, 3, 17), date(2026, 3, 18)),
            (date(2026, 4, 28), date(2026, 4, 29)),
            (date(2026, 6, 16), date(2026, 6, 17)),
            (date(2026, 7, 28), date(2026, 7, 29)),
            (date(2026, 9, 15), date(2026, 9, 16)),
            (date(2026, 10, 27), date(2026, 10, 28)),
            (date(2026, 12, 8), date(2026, 12, 9)),
        ]

    def test_eight_meetings_no_more_no_less(self):
        assert len(FOMC_DATES_2026) == 8


class TestGdp2025Dates:
    """Source: https://www.bea.gov/news/schedule (full-2025 tab, retrieved
    2026-07-21) plus
    https://www.bea.gov/news/2025/gross-domestic-product-3rd-quarter-2025-initial-estimate-and-corporate-profits
    for the Dec 23 Initial Estimate relabel."""

    def test_matches_bea_schedule_exactly(self):
        assert GDP_DATES_2025 == [
            (date(2025, 1, 30), "Q4 2024 Advance"),
            (date(2025, 2, 27), "Q4 2024 Second"),
            (date(2025, 3, 27), "Q4 2024 Third"),
            (date(2025, 4, 30), "Q1 2025 Advance"),
            (date(2025, 5, 29), "Q1 2025 Second"),
            (date(2025, 6, 26), "Q1 2025 Third"),
            (date(2025, 7, 30), "Q2 2025 Advance"),
            (date(2025, 8, 28), "Q2 2025 Second"),
            (date(2025, 9, 25), "Q2 2025 Third"),
            (date(2025, 12, 23), "Q3 2025 Initial Estimate"),
        ]

    def test_shutdown_cancellations_are_not_present(self):
        """Oct 30 (Advance) and Nov 26 (Second) were canceled by the Oct-Nov
        2025 shutdown and merged into the single Dec 23 Initial Estimate --
        they must not appear as separate entries."""
        dates = [d for d, _label in GDP_DATES_2025]
        assert date(2025, 10, 30) not in dates
        assert date(2025, 11, 26) not in dates
        assert dates.count(date(2025, 12, 23)) == 1


class TestGdp2026Dates:
    """Source: https://www.bea.gov/news/schedule (full-2026 / upcoming tab)
    plus the individual embargoed press releases cited in the block comment
    above GDP_DATES_2026 in seed_macro_events.py. Retrieved 2026-07-21."""

    def test_matches_bea_schedule_for_supported_non_colliding_dates(self):
        """Exact-equality on the seed list as shipped -- deliberately excludes
        both April-2026 BEA releases (see the collision test below)."""
        assert GDP_DATES_2026 == [
            (date(2026, 1, 22), "Q3 2025 Updated Estimate"),
            (date(2026, 2, 20), "Q4 2025 Advance"),
            (date(2026, 3, 13), "Q4 2025 Second"),
            (date(2026, 5, 28), "Q1 2026 Second"),
            (date(2026, 6, 25), "Q1 2026 Third"),
            (date(2026, 7, 30), "Q2 2026 Advance"),
            (date(2026, 8, 26), "Q2 2026 Second"),
            (date(2026, 9, 30), "Q2 2026 Third"),
            (date(2026, 10, 29), "Q3 2026 Advance"),
            (date(2026, 11, 25), "Q3 2026 Second"),
            (date(2026, 12, 23), "Q3 2026 Third"),
        ]

    def test_april_2026_structural_collision_is_reported_not_shoehorned(self):
        """Q4-2025 Third (Apr 9, corrected) and Q1-2026 Advance (Apr 30,
        corrected) both land in April 2026 -- one calendar month, two real
        releases. The recurrence-key MECHANICS are now fixed (see
        macro_recurrence_key's ``ordinal`` param + the accompanying
        migration), so encoding both would no longer collide -- but
        restoring these two real calendar entries is a separate data
        decision, deliberately left out of this list in this pass rather
        than bundled in unasked. This test pins that the omission here is
        still deliberate, not a leftover gap."""
        months = {d.month for d, _label in GDP_DATES_2026}
        assert 4 not in months
        dates = [d for d, _label in GDP_DATES_2026]
        assert date(2026, 4, 9) not in dates
        assert date(2026, 4, 30) not in dates
        assert date(2026, 4, 29) not in dates  # the old (wrong) guess either

    def test_no_second_shutdown_lapse_reflected_yet(self):
        """Q1-2026 Second/Third landed back on their originally-scheduled
        dates (confirmed via the individual BEA press pages), so the seed
        list's post-April entries are unchanged from the pre-fix list."""
        by_month = {d.month: label for d, label in GDP_DATES_2026}
        assert by_month[5] == "Q1 2026 Second"
        assert by_month[6] == "Q1 2026 Third"


class TestCpi2025Dates:
    """Source: Wayback Machine captures of
    https://www.bls.gov/schedule/news_release/cpi.htm (live bls.gov is
    HTTP-403-blocked; see the block comment above CPI_DATES_2025 in the
    script for the full capture list). Pre-shutdown baseline confirmed via
    https://web.archive.org/web/20250111210513/https://www.bls.gov/schedule/news_release/cpi.htm;
    shutdown-era corrections confirmed via
    https://web.archive.org/web/20251025032156/https://www.bls.gov/schedule/news_release/cpi.htm and
    https://web.archive.org/web/20251121185534/https://www.bls.gov/schedule/news_release/cpi.htm; the
    Feb-2026 second-lapse date confirmed via
    https://web.archive.org/web/20260213183647/https://www.bls.gov/schedule/news_release/cpi.htm."""

    def test_matches_bls_wayback_schedule_exactly(self):
        assert CPI_DATES_2025 == [
            date(2025, 1, 15),
            date(2025, 2, 12),
            date(2025, 3, 12),
            date(2025, 4, 10),
            date(2025, 5, 13),
            date(2025, 6, 11),
            date(2025, 7, 15),
            date(2025, 8, 12),
            date(2025, 9, 11),
            date(2025, 10, 24),
            date(2025, 12, 18),
        ]

    def test_october_shutdown_cancellation_is_not_present(self):
        """The Oct-2025 CPI was canceled outright by the Oct-Nov 2025
        shutdown -- the pre-fix guess (Nov 13, 2025) must not appear, and no
        entry should land in November 2025 data's place (only the real
        Nov-2025-data release, Dec 18, belongs in this list)."""
        assert date(2025, 11, 13) not in CPI_DATES_2025
        assert len(CPI_DATES_2025) == 11

    def test_known_wrong_examples_now_correct(self):
        assert date(2025, 10, 15) not in CPI_DATES_2025  # pre-shutdown Sep guess
        assert date(2025, 10, 24) in CPI_DATES_2025       # shutdown COLA release
        assert date(2025, 12, 10) not in CPI_DATES_2025  # pre-shutdown Nov guess
        assert date(2025, 12, 18) in CPI_DATES_2025       # shutdown-delayed


class TestCpi2026Dates:
    """Source: https://web.archive.org/web/20260702222336/https://www.bls.gov/schedule/news_release/cpi.htm
    (captured 2026-07-02, most recent full-year-coverage capture; the Feb 13
    second-lapse date additionally confirmed via
    https://web.archive.org/web/20260213183647/https://www.bls.gov/schedule/news_release/cpi.htm."""

    def test_matches_bls_wayback_schedule_exactly(self):
        assert CPI_DATES_2026 == [
            date(2026, 1, 13),
            date(2026, 2, 13),
            date(2026, 3, 11),
            date(2026, 4, 10),
            date(2026, 5, 12),
            date(2026, 6, 10),
            date(2026, 7, 14),
            date(2026, 8, 12),
            date(2026, 9, 11),
            date(2026, 10, 14),
            date(2026, 11, 10),
            date(2026, 12, 10),
        ]

    def test_twelve_months_no_more_no_less(self):
        assert len(CPI_DATES_2026) == 12

    def test_known_wrong_examples_now_correct(self):
        assert date(2026, 1, 14) not in CPI_DATES_2026  # pre-fix Dec-2025-data guess
        assert date(2026, 2, 11) not in CPI_DATES_2026  # pre-fix Jan-2026-data guess (second lapse moved it to 13)


class TestNfp2025Dates:
    """Source: Wayback Machine captures of
    https://www.bls.gov/schedule/news_release/empsit.htm (live bls.gov is
    HTTP-403-blocked; see the block comment above NFP_DATES_2025 in the
    script for the full capture list). Pre-shutdown baseline confirmed via
    https://web.archive.org/web/20250719172653/https://www.bls.gov/schedule/news_release/empsit.htm;
    post-shutdown corrections confirmed via
    https://web.archive.org/web/20251121185540/https://www.bls.gov/schedule/news_release/empsit.htm."""

    def test_matches_bls_wayback_schedule_exactly(self):
        assert NFP_DATES_2025 == [
            date(2025, 1, 10),
            date(2025, 2, 7),
            date(2025, 3, 7),
            date(2025, 4, 4),
            date(2025, 5, 2),
            date(2025, 6, 6),
            date(2025, 7, 3),
            date(2025, 8, 1),
            date(2025, 9, 5),
            date(2025, 11, 20),
            date(2025, 12, 16),
        ]

    def test_october_shutdown_cancellation_is_not_present(self):
        """The Oct-2025 jobs report was never separately published (folded
        into the next report) -- the pre-fix guess (Nov 7, 2025) must not
        appear."""
        assert date(2025, 11, 7) not in NFP_DATES_2025
        assert len(NFP_DATES_2025) == 11

    def test_known_wrong_examples_now_correct(self):
        assert date(2025, 10, 3) not in NFP_DATES_2025   # pre-shutdown Sep guess
        assert date(2025, 11, 20) in NFP_DATES_2025       # shutdown-delayed
        assert date(2025, 12, 5) not in NFP_DATES_2025   # pre-shutdown Nov guess
        assert date(2025, 12, 16) in NFP_DATES_2025       # shutdown-delayed


class TestNfp2026Dates:
    """Source: https://web.archive.org/web/20260702082019/https://www.bls.gov/schedule/news_release/empsit.htm
    (captured 2026-07-02, most recent full-year-coverage capture; the Feb 11
    second-lapse date additionally confirmed via
    https://web.archive.org/web/20260213183650/https://www.bls.gov/schedule/news_release/empsit.htm."""

    def test_matches_bls_wayback_schedule_exactly(self):
        assert NFP_DATES_2026 == [
            date(2026, 1, 9),
            date(2026, 2, 11),
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

    def test_twelve_months_no_more_no_less(self):
        assert len(NFP_DATES_2026) == 12

    def test_known_wrong_example_now_correct(self):
        """Jan-2026 jobs report's second-lapse move: originally-planned Feb
        6, 2026 moved to Feb 11, 2026."""
        assert date(2026, 2, 6) not in NFP_DATES_2026
        assert date(2026, 2, 11) in NFP_DATES_2026


class TestPce2025Dates:
    """Source: https://www.bea.gov/news/schedule/full-2025 (retrieved
    2026-08-14, issue #265). PCE was the one series neither issue-015 pass
    re-derived -- 2026-07-21 covered FOMC/GDP, 2026-07-23 covered CPI/NFP --
    so it still carried pre-audit guesses through the Oct-Nov 2025 shutdown."""

    def test_matches_bea_schedule_exactly(self):
        assert PCE_DATES_2025 == [
            date(2025, 1, 31),
            date(2025, 2, 28),
            date(2025, 3, 28),
            date(2025, 4, 30),
            date(2025, 5, 30),
            date(2025, 6, 27),
            date(2025, 7, 31),
            date(2025, 8, 29),
            date(2025, 9, 26),
            date(2025, 12, 5),
        ]

    def test_shutdown_corrections(self):
        """Sep-2025 data slipped Oct 31 -> Dec 5, 2025."""
        assert date(2025, 10, 31) not in PCE_DATES_2025  # pre-shutdown Sep guess
        assert date(2025, 12, 5) in PCE_DATES_2025       # shutdown-delayed

    def test_oct_and_nov_2025_have_no_2025_entries(self):
        """Oct-2025 and Nov-2025 data were never released separately in 2025 --
        BEA combined them into one Jan 22, 2026 release (asserted in the 2026
        test below). The old guesses must not linger, and the list must not
        gain a replacement entry in their place."""
        assert date(2025, 11, 26) not in PCE_DATES_2025
        assert date(2025, 12, 23) not in PCE_DATES_2025
        assert len(PCE_DATES_2025) == 10


class TestPce2026Dates:
    """Source: https://www.bea.gov/news/schedule/full (full-2026 tab, which
    lists already-published releases as well as upcoming; retrieved
    2026-08-14). The two shutdown-shifted spring dates are additionally
    confirmed by BEA's own reschedule notice:
    https://www.bea.gov/index.php/news/blog/2026-01-15/economic-release-schedule-updates-gdp-personal-income-and-outlays

    This list is the headline fix of issue #265: it never existed, so
    ``seed_statistical_specs`` gated PCE behind ``if year == 2025:`` and the
    2026 calendar silently carried no PCE row in any month."""

    def test_matches_bea_schedule_exactly(self):
        assert PCE_DATES_2026 == [
            date(2026, 1, 22),
            date(2026, 2, 20),
            date(2026, 3, 13),
            date(2026, 4, 9),
            date(2026, 4, 30),
            date(2026, 5, 28),
            date(2026, 6, 25),
            date(2026, 7, 30),
            date(2026, 8, 26),
            date(2026, 9, 30),
            date(2026, 10, 29),
            date(2026, 11, 25),
            date(2026, 12, 23),
        ]

    def test_thirteen_releases_because_of_the_catch_up(self):
        """Thirteen, not twelve: Jan 22 clears the combined Oct+Nov 2025
        backlog on top of the twelve regular Dec-2025..Nov-2026 prints."""
        assert len(PCE_DATES_2026) == 13
        assert date(2026, 1, 22) in PCE_DATES_2026

    def test_shutdown_shifted_spring_dates(self):
        """Jan-2026 data moved Feb 26 -> Mar 13; Feb-2026 data moved
        Mar 27 -> Apr 9 (BEA reschedule notice)."""
        assert date(2026, 2, 26) not in PCE_DATES_2026
        assert date(2026, 3, 13) in PCE_DATES_2026
        assert date(2026, 3, 27) not in PCE_DATES_2026
        assert date(2026, 4, 9) in PCE_DATES_2026

    def test_april_carries_both_real_releases(self):
        """April 2026 holds two real releases -- Feb-2026 data (Apr 9) and
        Mar-2026 data (Apr 30). Unlike the GDP April collision (still
        deliberately unencoded), both are seeded here; the recurrence-key
        disambiguation is asserted in TestMonthlyCollisionKeys below."""
        april = [d for d in PCE_DATES_2026 if d.month == 4]
        assert april == [date(2026, 4, 9), date(2026, 4, 30)]

    def test_post_april_dates_co_release_with_gdp(self):
        """From Mar-2026 data onward BEA co-releases PCE with that month's GDP
        estimate, so every PCE date from Apr 30 on must appear in
        GDP_DATES_2026 -- an independent cross-check that these dates were
        read off the right rows of the schedule table."""
        gdp_dates = {d for d, _label in GDP_DATES_2026}
        for d in PCE_DATES_2026:
            if d >= date(2026, 5, 1):
                assert d in gdp_dates, d


class TestPpi2026Dates:
    """Source: Wayback Machine captures of
    https://www.bls.gov/schedule/news_release/ppi.htm (live bls.gov is still
    HTTP-403-blocked from every egress tried, as of 2026-08-14):
    https://web.archive.org/web/20260731041441/https://www.bls.gov/schedule/news_release/ppi.htm
    (captured 2026-07-31, most recent) and
    https://web.archive.org/web/20260213183648/https://www.bls.gov/schedule/news_release/ppi.htm
    (captured 2026-02-13, earliest 2026). The two agree on every row, and the
    CDX digest is identical across the 2026-03-19/05-01/05-15/06-12/07-31
    captures -- the schedule has been stable since mid-March 2026."""

    def test_matches_bls_wayback_schedule_exactly(self):
        assert PPI_DATES_2026 == [
            date(2026, 1, 14),
            date(2026, 1, 30),
            date(2026, 2, 27),
            date(2026, 3, 18),
            date(2026, 4, 14),
            date(2026, 5, 13),
            date(2026, 6, 11),
            date(2026, 7, 15),
            date(2026, 8, 13),
            date(2026, 9, 10),
            date(2026, 10, 15),
            date(2026, 11, 13),
            date(2026, 12, 15),
        ]

    def test_thirteen_releases_because_of_the_catch_up(self):
        assert len(PPI_DATES_2026) == 13

    def test_january_carries_both_real_releases(self):
        """Nov-2025 data (Jan 14) and Dec-2025 data (Jan 30) -- the shutdown
        catch-up, two real PPI prints in one calendar month."""
        january = [d for d in PPI_DATES_2026 if d.month == 1]
        assert january == [date(2026, 1, 14), date(2026, 1, 30)]

    def test_july_print_that_gated_a_live_decision(self):
        """Jul-2026 data released Aug 13, 2026 -- the print behind the
        2026-08-13 gold bounce-confirm stand-down that surfaced this issue.
        Pinned because it is the one date here with a known decision
        attached to it."""
        assert date(2026, 8, 13) in PPI_DATES_2026


class TestSeriesCoverageIsDeclaredNotSilent:
    """Issue #265's root cause was shape, not data: PCE produced nothing for
    2026 because of an ``if year == 2025:`` nobody could see from the seeder's
    output. Coverage is now a declared table that every run prints."""

    def test_2026_covers_every_monthly_series(self):
        covered, gaps = series_coverage(2026)
        assert set(covered) == {"cpi", "nfp", "pce", "ppi"}
        assert gaps == []

    def test_2025_declares_its_ppi_gap_rather_than_hiding_it(self):
        """2025 PPI is deliberately not back-filled (past events, no decision
        rides on them, and it would need its own shutdown-era derivation).
        The point is that the gap is reported, not silent."""
        covered, gaps = series_coverage(2025)
        assert set(covered) == {"cpi", "nfp", "pce"}
        assert gaps == ["ppi"]

    def test_pce_is_actually_seeded_for_2026(self):
        """The regression that would reintroduce the bug: PCE specs present
        for 2026, not just for 2025."""
        pce = [s for s in seed_statistical_specs(2026) if s.event_type == "pce"]
        assert len(pce) == 13

    def test_ppi_is_actually_seeded_for_2026(self):
        ppi = [s for s in seed_statistical_specs(2026) if s.event_type == "ppi"]
        assert len(ppi) == 13

    def test_ppi_is_in_the_retirement_scope(self):
        """PPI must be in MACRO_SEED_EVENT_TYPES or orphan retirement would
        never be able to clean up a corrected PPI date."""
        assert "ppi" in MACRO_SEED_EVENT_TYPES


class TestSeedOnlySpecsSurviveTheLivePath:
    """``resolve_macro_specs`` replaces the whole statistical batch with the
    FRED feed when a key is configured. PPI is not in the live feed's
    ``RELEASE_IDS``, so without a seed-only batch it would vanish from the
    calendar the moment FRED_API_KEY was set -- a silent regression of exactly
    the kind this issue is about."""

    def test_ppi_is_seeded_alongside_the_live_feed(self):
        types = {s.event_type for s in seed_only_specs(2026)}
        assert types == {"ppi"}

    def test_fred_covered_series_are_not_duplicated(self):
        """CPI/NFP/GDP/PCE come from FRED on the live path, so they must NOT
        also appear in the seed-only batch or every one would be written
        twice under two sources."""
        types = {s.event_type for s in seed_only_specs(2026)}
        assert types.isdisjoint({"cpi", "nfp", "gdp", "pce"})

    def test_declared_gap_year_yields_nothing(self):
        assert seed_only_specs(2025) == []


class TestMonthlyCollisionKeys:
    """The two real same-month collisions, keyed rather than collapsed."""

    def test_pce_april_2026_keys_are_distinct(self):
        keys = {
            s.event_date: s.recurrence_key
            for s in seed_statistical_specs(2026)
            if s.event_type == "pce"
        }
        assert keys[date(2026, 4, 9)] == "pce_2026_04_release_1"
        assert keys[date(2026, 4, 30)] == "pce_2026_04_release_2"

    def test_ppi_january_2026_keys_are_distinct(self):
        keys = {
            s.event_date: s.recurrence_key
            for s in seed_statistical_specs(2026)
            if s.event_type == "ppi"
        }
        assert keys[date(2026, 1, 14)] == "ppi_2026_01_release_1"
        assert keys[date(2026, 1, 30)] == "ppi_2026_01_release_2"

    def test_ordinary_months_keep_legacy_month_only_keys(self):
        """Purely additive: no existing row is re-keyed, so this change needs
        no migration (unlike the GDP grain fix, which did)."""
        by_date = {
            s.event_date: s.recurrence_key
            for s in seed_statistical_specs(2026)
            if s.event_type in {"pce", "ppi"}
        }
        assert by_date[date(2026, 8, 26)] == "pce_2026_08"
        assert by_date[date(2026, 8, 13)] == "ppi_2026_08"

    def test_existing_pce_2025_keys_are_unchanged(self):
        """The 2025 PCE corrections move dates within their month, so every
        surviving row updates in place under its original key. Only the two
        removed entries (Oct/Nov) become orphans for the retirement pass."""
        keys = {
            s.recurrence_key
            for s in seed_statistical_specs(2025)
            if s.event_type == "pce"
        }
        assert keys == {f"pce_2025_{m:02d}" for m in list(range(1, 10)) + [12]}


class TestSeedSpecsStillDedupClean:
    """Guards that the corrections above don't reintroduce a recurrence-key
    collision through seed_statistical_specs (the function the seeder
    actually calls) -- belt-and-suspenders on top of the existing
    TestSeedSpecsDedup in test_fred_provider.py."""

    def test_2025_specs_have_unique_recurrence_keys(self):
        specs = seed_statistical_specs(2025)
        keys = [s.recurrence_key for s in specs]
        assert len(keys) == len(set(keys))

    def test_2026_specs_have_unique_recurrence_keys(self):
        specs = seed_statistical_specs(2026)
        keys = [s.recurrence_key for s in specs]
        assert len(keys) == len(set(keys))


class TestGdpOrdinalLabelParsing:
    """GDP recurrence-key grain fix: the seed list's label text is the
    authoritative source for a GDP row's ordinal (unlike the live FRED feed,
    which only gets a bare date -- see fred.gdp_estimate_ordinal)."""

    def test_advance_second_third(self):
        assert _gdp_ordinal("Q4 2024 Advance") == "advance"
        assert _gdp_ordinal("Q4 2024 Second") == "second"
        assert _gdp_ordinal("Q4 2024 Third") == "third"

    def test_shutdown_relabeled_variants(self):
        assert _gdp_ordinal("Q3 2025 Initial Estimate") == "initial_estimate"
        assert _gdp_ordinal("Q3 2025 Updated Estimate") == "updated_estimate"

    def test_initial_estimate_not_mistaken_for_third(self):
        """"Initial Estimate" doesn't contain the substring "Third" -- pin
        that the more-specific token is matched instead of falling through
        to an unrelated shorter token by accident."""
        assert _gdp_ordinal("Q3 2025 Initial Estimate") != "third"

    def test_every_2025_and_2026_label_produces_a_recognized_ordinal(self):
        recognized = {
            "advance", "second", "third", "initial_estimate", "updated_estimate",
        }
        for _d, label in GDP_DATES_2025 + GDP_DATES_2026:
            assert _gdp_ordinal(label) in recognized, label


class TestGdpAdvanceEquivalentImportance:
    """Importance-heuristic drift fix: a government-shutdown-relabeled
    "Initial Estimate" release is the Advance-equivalent for importance
    purposes even though it doesn't contain the substring "Advance"."""

    def test_advance_is_advance_equivalent(self):
        assert _is_advance_equivalent("Q1 2025 Advance") is True

    def test_initial_estimate_is_advance_equivalent(self):
        assert _is_advance_equivalent("Q3 2025 Initial Estimate") is True

    def test_second_and_third_are_not(self):
        assert _is_advance_equivalent("Q1 2025 Second") is False
        assert _is_advance_equivalent("Q1 2025 Third") is False

    def test_updated_estimate_is_not_advance_equivalent(self):
        """"Updated Estimate" replaces a would-be Third estimate, not an
        Advance -- it must stay "medium", unchanged from before this fix."""
        assert _is_advance_equivalent("Q3 2025 Updated Estimate") is False

    def test_real_seed_list_entry_now_tagged_high(self):
        """The actual Dec 23, 2025 "Q3 2025 Initial Estimate" entry in the
        seed list -- previously silently dropped to "medium" importance by
        the old substring-only "Advance" check -- is now "high"."""
        specs = seed_statistical_specs(2025)
        initial_estimate = next(
            s for s in specs
            if s.event_type == "gdp" and "Initial Estimate" in s.title
        )
        assert initial_estimate.importance == "high"


class TestGdpSpecsCarryOrdinalKeys:
    """seed_statistical_specs (the function the seeder actually calls) now
    produces month+ordinal GDP keys, not the old collision-prone month-only
    keys."""

    def test_2025_gdp_keys_carry_ordinal_suffix(self):
        specs = [s for s in seed_statistical_specs(2025) if s.event_type == "gdp"]
        assert specs  # sanity: GDP is actually present
        for s in specs:
            assert s.recurrence_key.startswith("gdp_2025_")
            # month-only keys are exactly 12 chars ("gdp_YYYY_MM"); anything
            # produced here must be longer (has an ordinal suffix).
            assert len(s.recurrence_key) > len("gdp_2025_01")

    def test_advance_and_third_keys_for_a_known_pair(self):
        specs = {
            s.title: s.recurrence_key
            for s in seed_statistical_specs(2025)
            if s.event_type == "gdp"
        }
        assert specs["GDP Q4 2024 Advance"] == "gdp_2025_01_advance"
        assert specs["GDP Q4 2024 Third"] == "gdp_2025_03_third"
