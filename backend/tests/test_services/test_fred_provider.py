"""Tests for the FRED live macro-calendar provider and seed fallback.

These run without a database or network: the pure parser is exercised against a
real-shaped FRED payload, spec-building / recurrence-key dedup is asserted
directly, and the seed-vs-live resolution is driven with a fake provider so the
"fall back to seed when the key is absent" path is covered.
"""

from datetime import date, time

import pytest

from app.db.models.economic_event import EventSource, EventType
from app.services.data_providers.fred import (
    RELEASE_IDS,
    FredCalendarProvider,
    MacroEventSpec,
    gdp_estimate_ordinal,
    macro_recurrence_key,
)
from scripts.seed_macro_events import (
    resolve_macro_specs,
    seed_statistical_specs,
)


# A real-shaped fred/release/dates payload (CPI, release_id=10). Includes a
# future scheduled date, an out-of-year date, and — deliberately — a duplicate
# and a malformed row to prove the parser is defensive.
FRED_CPI_PAYLOAD = {
    "realtime_start": "2026-01-01",
    "realtime_end": "9999-12-31",
    "order_by": "release_date",
    "sort_order": "asc",
    "count": 5,
    "offset": 0,
    "limit": 10000,
    "release_dates": [
        {"release_id": 10, "date": "2025-12-10"},
        {"release_id": 10, "date": "2026-01-14"},
        {"release_id": 10, "date": "2026-02-11"},
        {"release_id": 10, "date": "2026-02-11"},  # duplicate
        {"release_id": 10, "date": "not-a-date"},  # malformed
        {"release_id": 10},  # missing date
    ],
}


class TestParseReleaseDates:
    def test_parses_sorts_and_dedupes(self):
        dates = FredCalendarProvider.parse_release_dates(FRED_CPI_PAYLOAD)
        assert dates == [
            date(2025, 12, 10),
            date(2026, 1, 14),
            date(2026, 2, 11),
        ]

    def test_missing_key_returns_empty(self):
        assert FredCalendarProvider.parse_release_dates({}) == []

    def test_non_list_release_dates_returns_empty(self):
        assert FredCalendarProvider.parse_release_dates({"release_dates": None}) == []


class TestRecurrenceKey:
    def test_monthly_key_matches_seed_scheme(self):
        assert macro_recurrence_key(EventType.CPI, date(2026, 2, 11)) == "cpi_2026_02"
        assert macro_recurrence_key(EventType.NFP, date(2026, 3, 6)) == "nfp_2026_03"
        assert macro_recurrence_key(EventType.PCE, date(2025, 1, 31)) == "pce_2025_01"
        assert macro_recurrence_key(EventType.FOMC, date(2026, 1, 28)) == "fomc_2026_01"

    def test_gdp_key_is_month_bucketed_and_self_healing(self):
        # Without an explicit ordinal, GDP still collapses on (year, month) --
        # a moved GDP date within the month self-heals in place, unchanged
        # from before the GDP recurrence-key grain fix.
        assert macro_recurrence_key(EventType.GDP, date(2026, 1, 29)) == "gdp_2026_01"
        assert macro_recurrence_key(EventType.GDP, date(2026, 1, 30)) == "gdp_2026_01"

    def test_non_gdp_key_unaffected_by_ordinal_param_when_omitted(self):
        """Every non-GDP caller today omits ``ordinal`` -- the key format for
        them must be byte-for-byte unchanged by the GDP grain fix."""
        assert macro_recurrence_key(EventType.CPI, date(2026, 2, 11)) == "cpi_2026_02"


class TestRecurrenceKeyOrdinal:
    """GDP recurrence-key grain fix: an explicit ``ordinal`` disambiguates two
    same-month GDP prints (e.g. a shutdown-delayed Third landing in the same
    month as the next quarter's Advance) instead of colliding under one key."""

    def test_ordinal_appends_a_slugified_suffix(self):
        assert (
            macro_recurrence_key(EventType.GDP, date(2026, 4, 9), ordinal="Third")
            == "gdp_2026_04_third"
        )
        assert (
            macro_recurrence_key(EventType.GDP, date(2026, 4, 30), ordinal="Advance")
            == "gdp_2026_04_advance"
        )

    def test_same_month_different_ordinal_keys_are_distinct(self):
        third = macro_recurrence_key(EventType.GDP, date(2026, 4, 9), ordinal="Third")
        advance = macro_recurrence_key(EventType.GDP, date(2026, 4, 30), ordinal="Advance")
        assert third != advance

    def test_ordinal_is_slugified(self):
        key = macro_recurrence_key(
            EventType.GDP, date(2025, 12, 23), ordinal="Initial Estimate"
        )
        assert key == "gdp_2025_12_initial_estimate"

    def test_empty_ordinal_string_behaves_like_none(self):
        assert (
            macro_recurrence_key(EventType.GDP, date(2026, 4, 9), ordinal="")
            == "gdp_2026_04"
        )


class TestGdpEstimateOrdinal:
    """Best-effort Advance/Second/Third inference for the live FRED path,
    which only ever gets a bare date (no per-estimate label)."""

    def test_normal_cadence_months_map_correctly(self):
        # Matches the real, undisrupted 2025 GDP cadence in the seed list:
        # Jan/Apr/Jul/Oct=advance, Feb/May/Aug/Nov=second, Mar/Jun/Sep/Dec=third.
        assert gdp_estimate_ordinal(date(2025, 1, 30)) == "advance"
        assert gdp_estimate_ordinal(date(2025, 2, 27)) == "second"
        assert gdp_estimate_ordinal(date(2025, 3, 27)) == "third"
        assert gdp_estimate_ordinal(date(2025, 4, 30)) == "advance"
        assert gdp_estimate_ordinal(date(2025, 5, 29)) == "second"
        assert gdp_estimate_ordinal(date(2025, 6, 26)) == "third"

    def test_every_month_maps_to_exactly_one_of_the_three_ordinals(self):
        results = {gdp_estimate_ordinal(date(2026, m, 15)) for m in range(1, 13)}
        assert results == {"advance", "second", "third"}


class TestDatesToSpecs:
    def test_filters_to_year_and_builds_specs(self):
        provider = FredCalendarProvider(api_key="test")
        dates = [date(2025, 12, 10), date(2026, 1, 14), date(2026, 2, 11)]
        specs = provider._dates_to_specs(EventType.CPI, dates, 2026)

        assert {s.recurrence_key for s in specs} == {"cpi_2026_01", "cpi_2026_02"}
        for s in specs:
            assert s.event_type == EventType.CPI.value
            assert s.title == "CPI Report"
            assert s.importance == "high"
            assert s.event_time == time(8, 30)
            assert s.all_day is False

    def test_same_month_dates_both_persist(self):
        """BEHAVIOR CHANGE (issue #265). This test previously asserted the
        OPPOSITE -- that two same-month dates of a monthly series collapse to
        one spec -- on the assumption that a monthly series publishes once per
        calendar month, so a second date had to be noise.

        The 2025-26 shutdown cascade falsified that assumption twice with real
        releases: BLS published PPI for Nov-2025 data on Jan 14, 2026 AND for
        Dec-2025 data on Jan 30, 2026; BEA published Personal Income and
        Outlays for Feb-2026 data on Apr 9, 2026 AND for Mar-2026 data on
        Apr 30, 2026. Collapsing silently threw away one real, decision-gating
        release -- the same bug already fixed for GDP, and only for GDP.

        The failure modes are not symmetric: collapsing loses a release with
        no trace, whereas splitting a genuinely spurious duplicate shows one
        extra calendar row. The visible failure is the right one to prefer.
        """
        provider = FredCalendarProvider(api_key="test")
        specs = provider._dates_to_specs(
            EventType.CPI, [date(2026, 2, 11), date(2026, 2, 12)], 2026
        )
        assert len(specs) == 2
        assert {s.event_date for s in specs} == {date(2026, 2, 11), date(2026, 2, 12)}
        assert {s.recurrence_key for s in specs} == {
            "cpi_2026_02_release_1",
            "cpi_2026_02_release_2",
        }

    def test_ordinary_single_release_month_keeps_the_legacy_key(self):
        """The disambiguation is purely additive: a month with exactly one
        release keeps the plain ``<type>_<year>_<month>`` key byte-for-byte,
        so no existing CPI/NFP/PCE row is re-keyed and no migration is needed.
        """
        provider = FredCalendarProvider(api_key="test")
        specs = provider._dates_to_specs(EventType.CPI, [date(2026, 2, 13)], 2026)
        assert [s.recurrence_key for s in specs] == ["cpi_2026_02"]

    def test_gdp_specs_get_ordinal_suffixed_keys(self):
        provider = FredCalendarProvider(api_key="test")
        specs = provider._dates_to_specs(EventType.GDP, [date(2026, 1, 29)], 2026)
        assert len(specs) == 1
        assert specs[0].recurrence_key == "gdp_2026_01_advance"

    def test_gdp_same_month_different_estimates_both_persist(self):
        """The mechanics fix's core case: two GDP prints landing in the same
        calendar month (e.g. a shutdown-delayed Third alongside the next
        quarter's Advance -- the real Apr 2026 collision this PR cites) must
        NOT collide into one spec anymore. Both dates are in month 4, so the
        month-only ``gdp_estimate_ordinal`` heuristic alone can't tell them
        apart -- the collision-aware positional fallback (release_1/2) does."""
        provider = FredCalendarProvider(api_key="test")
        specs = provider._dates_to_specs(
            EventType.GDP, [date(2026, 4, 9), date(2026, 4, 30)], 2026
        )
        assert len(specs) == 2
        event_dates = {s.event_date for s in specs}
        assert event_dates == {date(2026, 4, 9), date(2026, 4, 30)}
        keys = {s.recurrence_key for s in specs}
        assert keys == {"gdp_2026_04_release_1", "gdp_2026_04_release_2"}


class TestKeyGating:
    def test_unconfigured_is_not_configured(self):
        assert FredCalendarProvider(api_key="").is_configured is False

    def test_configured_when_key_present(self):
        assert FredCalendarProvider(api_key="abc123").is_configured is True

    @pytest.mark.asyncio
    async def test_unconfigured_get_macro_events_returns_empty_without_http(self):
        provider = FredCalendarProvider(api_key="")

        async def _boom(*args, **kwargs):  # would raise if fetch were attempted
            raise AssertionError("network must not be hit when unconfigured")

        provider.get_release_dates = _boom  # type: ignore[assignment]
        assert await provider.get_macro_events(2026) == []


class TestGetMacroEventsLive:
    @pytest.mark.asyncio
    async def test_builds_specs_for_all_releases_from_live_dates(self, monkeypatch):
        provider = FredCalendarProvider(api_key="test")

        # Map release_id -> a representative date, bypassing the network.
        fixture = {
            RELEASE_IDS[EventType.CPI]: [date(2026, 1, 14)],
            RELEASE_IDS[EventType.NFP]: [date(2026, 1, 9)],
            RELEASE_IDS[EventType.GDP]: [date(2026, 1, 29)],
            RELEASE_IDS[EventType.PCE]: [date(2026, 1, 31)],
        }

        async def fake_get_release_dates(release_id, year):
            return fixture[release_id]

        monkeypatch.setattr(provider, "get_release_dates", fake_get_release_dates)

        specs = await provider.get_macro_events(2026)
        keys = {s.recurrence_key for s in specs}
        # GDP now carries its ordinal suffix (Jan -> "advance" under the
        # month-mod-3 heuristic, the single-date-per-month common case) --
        # the other types are unaffected by the GDP grain fix.
        assert keys == {
            "cpi_2026_01",
            "nfp_2026_01",
            "gdp_2026_01_advance",
            "pce_2026_01",
        }


class TestResolveMacroSpecs:
    """Seed-vs-live selection — the graceful fallback contract."""

    @pytest.mark.asyncio
    async def test_falls_back_to_seed_when_key_absent(self):
        provider = FredCalendarProvider(api_key="")  # not configured
        batches = await resolve_macro_specs(provider, 2026, use_live=True)

        sources = {src for _, src in batches}
        # No FRED batch; everything seeded.
        assert EventSource.FRED.value not in sources
        assert sources == {EventSource.SEED.value}

        # FOMC + the statistical seed lists are all present.
        all_types = {s.event_type for specs, _ in batches for s in specs}
        assert EventType.FOMC.value in all_types
        assert EventType.CPI.value in all_types
        assert EventType.NFP.value in all_types

    @pytest.mark.asyncio
    async def test_uses_live_when_configured_and_data_returned(self, monkeypatch):
        provider = FredCalendarProvider(api_key="test")

        live = [
            MacroEventSpec(
                event_type=EventType.CPI.value,
                event_date=date(2027, 1, 13),
                recurrence_key="cpi_2027_01",
                title="CPI Report",
                description="x",
                importance="high",
                event_time=time(8, 30),
            )
        ]

        async def fake_get_macro_events(year):
            return live

        monkeypatch.setattr(provider, "get_macro_events", fake_get_macro_events)

        batches = await resolve_macro_specs(provider, 2027, use_live=True)
        by_source = {src: specs for specs, src in batches}

        # FOMC seeded, statistical rows come from the live FRED batch.
        assert EventSource.SEED.value in by_source  # FOMC
        assert by_source[EventSource.FRED.value] == live

    @pytest.mark.asyncio
    async def test_falls_back_when_live_returns_empty(self, monkeypatch):
        provider = FredCalendarProvider(api_key="test")

        async def empty(year):
            return []

        monkeypatch.setattr(provider, "get_macro_events", empty)

        batches = await resolve_macro_specs(provider, 2026, use_live=True)
        assert EventSource.FRED.value not in {src for _, src in batches}


class TestSeedSpecsDedup:
    def test_seed_specs_have_unique_recurrence_keys(self):
        specs = seed_statistical_specs(2026)
        keys = [s.recurrence_key for s in specs]
        assert len(keys) == len(set(keys))  # no dupes within a year

    def test_live_and_seed_share_key_scheme(self):
        """A live CPI date and the seeded CPI date for the same month collide on
        recurrence_key — so a live refresh updates the seeded row in place."""
        seed = {s.recurrence_key for s in seed_statistical_specs(2026)
                if s.event_type == EventType.CPI.value}
        live_key = macro_recurrence_key(EventType.CPI, date(2026, 1, 30))
        # Seeded Jan CPI key exists and equals the live Jan key regardless of day.
        assert "cpi_2026_01" in seed
        assert live_key == "cpi_2026_01"
