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
        # One GDP print per calendar month -> month bucket, so a moved GDP date
        # within the month collapses to the same key (self-heals in place).
        assert macro_recurrence_key(EventType.GDP, date(2026, 1, 29)) == "gdp_2026_01"
        assert macro_recurrence_key(EventType.GDP, date(2026, 1, 30)) == "gdp_2026_01"


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

    def test_same_month_dates_collapse_to_one_spec(self):
        provider = FredCalendarProvider(api_key="test")
        # Two dates in the same month must not produce two specs (monthly key).
        specs = provider._dates_to_specs(
            EventType.CPI, [date(2026, 2, 11), date(2026, 2, 12)], 2026
        )
        assert len(specs) == 1


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
        assert keys == {"cpi_2026_01", "nfp_2026_01", "gdp_2026_01", "pce_2026_01"}


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
