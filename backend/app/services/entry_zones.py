"""Tiered entry-zone status - the shared builder.

The watchlist API (live quote), the context pack (latest stored close), and
the entry_zone alert evaluator (check-cycle price) all derive zone status
from these functions so the three surfaces cannot drift.

A zone is a named price band with at least one bound. Status relative to a
price:

- ``in_zone``     - price within the bounds
- ``approaching`` - price outside on the entry side, within
                    APPROACHING_THRESHOLD_PCT of the entry edge
- ``above``       - price above the zone (for zones entered from above)
- ``below``       - price below the zone's low (fell through / not yet risen
                    into a low-only zone)

The "entry side" is above the high bound for zones with a high (the normal
buy-the-dip case), and below the low bound for low-only zones.
"""

from decimal import Decimal
from typing import List, Optional, Tuple

from app.schemas.watchlist import EntryZone, EntryZoneStatus

# Mirrors the context pack's alert "approaching" threshold
APPROACHING_THRESHOLD_PCT = Decimal("3")


def parse_zones(raw: Optional[list]) -> List[EntryZone]:
    """Parse the JSONB list stored on a watchlist item (bounds are strings)."""
    if not raw:
        return []
    return [EntryZone.model_validate(z) for z in raw]


def zone_entry_edge(zone: EntryZone) -> Decimal:
    """The bound the price crosses to enter the zone.

    High-bounded zones are entered from above (price falls to the high);
    low-only zones are entered from below (price rises to the low).
    """
    return zone.high if zone.high is not None else zone.low  # type: ignore[return-value]


def is_in_zone(price: Decimal, zone: EntryZone) -> bool:
    """Whether a price is within the zone's bounds."""
    if zone.low is not None and price < zone.low:
        return False
    if zone.high is not None and price > zone.high:
        return False
    return True


def zone_status(
    price: Decimal, zone: EntryZone
) -> Tuple[str, Optional[Decimal]]:
    """Status plus signed percent distance to the entry edge.

    Distance is the percent move from the price to the edge (negative =
    price must fall); None when in the zone.
    """
    if is_in_zone(price, zone):
        return "in_zone", None

    edge = zone_entry_edge(zone)
    distance = (
        ((edge - price) / price * 100).quantize(Decimal("0.01"))
        if price != 0
        else None
    )

    if zone.high is not None and price > zone.high:
        side = "above"
    else:
        side = "below"

    on_entry_side = (zone.high is not None and side == "above") or (
        zone.high is None and side == "below"
    )
    if (
        on_entry_side
        and distance is not None
        and abs(distance) <= APPROACHING_THRESHOLD_PCT
    ):
        return "approaching", distance
    return side, distance


def build_zone_statuses(
    price: Optional[Decimal], zones: List[EntryZone]
) -> List[EntryZoneStatus]:
    """Zone statuses for a price; status 'unknown' when no price is available."""
    statuses: List[EntryZoneStatus] = []
    for zone in zones:
        if price is None:
            status, distance = "unknown", None
        else:
            status, distance = zone_status(price, zone)
        statuses.append(
            EntryZoneStatus(
                tier=zone.tier,
                low=zone.low,
                high=zone.high,
                status=status,
                distance_percent=distance,
            )
        )
    return statuses
