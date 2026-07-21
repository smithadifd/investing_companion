"""Regression fixtures pinning the issue-015 calendar-accuracy corrections.

Network- and DB-free: exercises the raw hand-maintained date lists in
``scripts/seed_macro_events`` directly. Every expected dataset here sits next
to the official primary source that pins it (retrieved 2026-07-21) so a future
regression trips against a cited receipt, not a guess.

Scope of this pass (see the block comments in seed_macro_events.py for the
full derivation):
  - FOMC 2025 + 2026: fully re-derived from federalreserve.gov (reachable).
  - GDP 2025 + 2026: fully re-derived from bea.gov (reachable), including the
    Oct-Nov 2025 shutdown's cancellations/mergers and one reported (not
    resolved) structural collision in April 2026.
  - CPI / NFP: NOT re-derived -- bls.gov was unreachable (HTTP 403 / DNS
    failure on every path tried) for this pass's fetch tooling, so those seed
    lists are untouched and have no new fixtures here. See the block comments
    above ``CPI_DATES_2025``/``NFP_DATES_2025`` in the script.
"""

from datetime import date

from scripts.seed_macro_events import (
    FOMC_DATES_2025,
    FOMC_DATES_2026,
    GDP_DATES_2025,
    GDP_DATES_2026,
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
        """The #36 verifier's receipts: both meetings were guessed a week-plus
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

    def test_matches_bea_schedule_exactly(self):
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
        releases. The month-bucketed recurrence_key (macro_recurrence_key in
        fred.py) can only hold one GDP row per month, so fixing the mechanics
        is out of scope here; neither date is shoehorned into the seed list.
        This test pins that the omission is deliberate, not a leftover gap."""
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
