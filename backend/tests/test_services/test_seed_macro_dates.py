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
    NFP_DATES_2025,
    NFP_DATES_2026,
    _gdp_ordinal,
    _is_advance_equivalent,
    seed_statistical_specs,
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
