"""FRED (St. Louis Fed) live macro-release calendar provider.

Replaces the hand-maintained FOMC/CPI/NFP/GDP/PCE date lists in
``scripts/seed_macro_events.py`` with a live feed of scheduled release dates, so
the calendar stays self-healing instead of going dry once the hardcoded years
run out (issue 015).

The feed is **key-gated**: FRED needs a free API key
(https://fredaccount.stlouisfed.org/apikeys). When ``FRED_API_KEY`` is unset the
provider reports ``is_configured == False`` and every fetch returns an empty
list, so the seeder falls back to its hand-maintained lists rather than crashing.

Only the four statistical releases FRED actually tracks are covered here
(CPI/NFP/GDP/PCE). FOMC meeting dates are **not** a FRED "release" — the Fed
publishes them a year ahead on its own calendar and they rarely move, so they
stay seeded (handled by the seeder, not this provider).

The produced :class:`MacroEventSpec` objects carry the same ``recurrence_key``
scheme the seeder uses, so live and seeded events flow through the identical
``economic_events`` recurrence-key dedup path — the live feed never bypasses it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time
from typing import Optional

import httpx

from app.core.config import settings
from app.db.models.economic_event import EventType

logger = logging.getLogger(__name__)

FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# FRED release IDs for the statistical releases we surface. These are stable,
# public IDs (browse them at https://fred.stlouisfed.org/releases). If FRED ever
# renumbers one, it's a one-line fix here — the parsing/dedup logic is unaffected.
#   10 = Consumer Price Index
#   50 = Employment Situation (Non-Farm Payrolls / Jobs Report)
#   53 = Gross Domestic Product
#   54 = Personal Income and Outlays (carries the PCE price index)
RELEASE_IDS: dict[EventType, int] = {
    EventType.CPI: 10,
    EventType.NFP: 50,
    EventType.GDP: 53,
    EventType.PCE: 54,
}


@dataclass(frozen=True)
class MacroEventSpec:
    """A macro-release calendar entry, source-agnostic.

    Both the live FRED provider and the hand-maintained seed lists emit these,
    so a single upsert path (keyed on ``recurrence_key``) dedups them. The
    ``recurrence_key`` is the dedup identity — it MUST match the seeder's scheme
    so a live refresh updates the seeded row in place instead of duplicating it.
    """

    event_type: str
    event_date: date
    recurrence_key: str
    title: str
    description: str
    importance: str
    event_time: Optional[time] = None
    all_day: bool = False
    is_confirmed: bool = True


# Per-event-type presentation metadata, mirroring the seeder so live and seeded
# rows look identical on the calendar.
_EVENT_META: dict[EventType, dict] = {
    EventType.CPI: {
        "time": time(8, 30),
        "title": "CPI Report",
        "description": (
            "Consumer Price Index release. Key inflation indicator tracked by "
            "markets and the Fed."
        ),
        "importance": "high",
    },
    EventType.NFP: {
        "time": time(8, 30),
        "title": "Non-Farm Payrolls",
        "description": (
            "Monthly employment situation report. Includes job growth, "
            "unemployment rate, and wage data."
        ),
        "importance": "high",
    },
    EventType.GDP: {
        "time": time(8, 30),
        "title": "GDP Release",
        "description": "Gross Domestic Product report. Measures total economic output.",
        "importance": "medium",
    },
    EventType.PCE: {
        "time": time(8, 30),
        "title": "PCE Price Index",
        "description": (
            "Personal Income and Outlays. Carries the PCE price index — the "
            "Fed's preferred inflation measure."
        ),
        "importance": "medium",
    },
}


def macro_recurrence_key(event_type: EventType, d: date) -> str:
    """Build the dedup key for a macro event: ``<type>_<year>_<month>``.

    Keyed on the release's *occurrence* (year + month), NOT the publication day,
    so a moved date within the month updates the existing row in place instead
    of duplicating — the issue-015 self-heal, uniformly across every macro type.

    This holds for GDP too: the release schedule has exactly one GDP print per
    calendar month (a quarter's Advance, Second, and Third estimates land in
    three consecutive months), so a month bucket identifies it unambiguously.
    """
    return f"{event_type.value}_{d.year}_{d.month:02d}"


class FredCalendarProvider:
    """Fetches scheduled macro-release dates from the FRED API."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key if api_key is not None else settings.FRED_API_KEY

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    # ------------------------------------------------------------------
    # Pure parsing (unit-tested without network or DB)
    # ------------------------------------------------------------------
    @staticmethod
    def parse_release_dates(payload: dict) -> list[date]:
        """Parse a fred/release/dates JSON payload into sorted, unique dates.

        FRED shape::

            {"release_dates": [{"release_id": 10, "date": "2026-01-14"}, ...]}

        Malformed / undated entries are skipped rather than raising, so a partial
        or unexpected response degrades to whatever parsed cleanly.
        """
        rows = payload.get("release_dates")
        if not isinstance(rows, list):
            return []

        seen: set[date] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw = row.get("date")
            if not isinstance(raw, str):
                continue
            try:
                seen.add(date.fromisoformat(raw.strip()))
            except ValueError:
                logger.debug("Skipping unparseable FRED release date: %r", raw)
                continue

        return sorted(seen)

    def _dates_to_specs(
        self, event_type: EventType, dates: list[date], year: int
    ) -> list[MacroEventSpec]:
        """Turn raw release dates into deduped specs for a single year."""
        meta = _EVENT_META[event_type]
        specs: dict[str, MacroEventSpec] = {}
        for d in dates:
            if d.year != year:
                continue
            key = macro_recurrence_key(event_type, d)
            # Last-write-wins within a run; keys are stable so this is idempotent.
            specs[key] = MacroEventSpec(
                event_type=event_type.value,
                event_date=d,
                recurrence_key=key,
                title=meta["title"],
                description=meta["description"],
                importance=meta["importance"],
                event_time=meta["time"],
            )
        return list(specs.values())

    # ------------------------------------------------------------------
    # Network
    # ------------------------------------------------------------------
    async def get_release_dates(self, release_id: int, year: int) -> list[date]:
        """Fetch scheduled release dates for one FRED release in ``year``.

        ``include_release_dates_with_no_data=true`` returns *future* scheduled
        dates (not just those with published data). Returns ``[]`` on any error
        so callers degrade to the seed lists.
        """
        if not self.is_configured:
            return []

        params = {
            "release_id": release_id,
            "api_key": self._api_key,
            "file_type": "json",
            "include_release_dates_with_no_data": "true",
            "realtime_start": f"{year}-01-01",
            "realtime_end": "9999-12-31",
            "sort_order": "asc",
            "limit": 10000,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{FRED_BASE_URL}/release/dates", params=params
                )
                response.raise_for_status()
                return self.parse_release_dates(response.json())
        except httpx.HTTPStatusError as e:
            logger.error(
                "FRED release/dates error (release_id=%s): %s",
                release_id,
                e.response.status_code,
            )
            return []
        except Exception as e:  # noqa: BLE001 — never let a feed error crash seeding
            logger.error("Failed to fetch FRED release %s: %s", release_id, e)
            return []

    async def get_macro_events(self, year: int) -> list[MacroEventSpec]:
        """Fetch all covered macro releases for ``year`` as deduped specs.

        Empty list when unconfigured or when every fetch failed — the signal for
        the seeder to fall back to its hand-maintained lists.
        """
        if not self.is_configured:
            logger.info("FRED_API_KEY not set; live macro calendar disabled")
            return []

        all_specs: list[MacroEventSpec] = []
        for event_type, release_id in RELEASE_IDS.items():
            dates = await self.get_release_dates(release_id, year)
            all_specs.extend(self._dates_to_specs(event_type, dates, year))

        logger.info("FRED live macro calendar: %d events for %d", len(all_specs), year)
        return all_specs
