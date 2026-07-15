"""Tests for tiered entry zones: status builder, zone-hit alerts, zones CRUD."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.alert import AlertConditionType, AlertCreate, AlertUpdate
from app.schemas.equity import QuoteResponse
from app.schemas.watchlist import EntryZone, WatchlistItemCreate, WatchlistItemUpdate
from app.services.alert import AlertService
from app.services.entry_zones import (
    build_zone_statuses,
    parse_zones,
    zone_status,
)
from app.services.watchlist import WatchlistService
from tests.factories import (
    create_test_equity,
    create_test_watchlist,
    create_test_watchlist_item,
)

# The EQT May-12 tiered framework: $50-52 half starter / $47-48 full add /
# sub-46 aggressive
EQT_ZONES = [
    {"tier": "Half starter", "low": "50", "high": "52"},
    {"tier": "Full add", "low": "47", "high": "48"},
    {"tier": "Aggressive", "low": None, "high": "46"},
]


def _quote(price: float) -> QuoteResponse:
    return QuoteResponse(
        symbol="TEST",
        price=price,
        change=0.0,
        change_percent=0.0,
        volume=1_000_000,
        high=price,
        low=price,
        open=price,
        previous_close=price,
        market_cap=None,
        timestamp=datetime.now(timezone.utc),
    )


async def _zone_item(db, *, symbol="EQT", zones=None):
    equity = await create_test_equity(db, symbol=symbol)
    wl = await create_test_watchlist(db, name=f"WL {symbol}")
    item = await create_test_watchlist_item(
        db, wl, equity, entry_zones=zones if zones is not None else EQT_ZONES
    )
    return equity, item


def _zone_service(db, price: float | None) -> AlertService:
    service = AlertService(db)
    mock_yahoo = AsyncMock()
    mock_yahoo.get_quote = AsyncMock(
        return_value=_quote(price) if price is not None else None
    )
    service.yahoo = mock_yahoo
    return service


# ---------------------------------------------------------------------------
# Status builder
# ---------------------------------------------------------------------------

class TestZoneStatus:
    def test_in_zone_both_bounds(self):
        zone = EntryZone(tier="t", low=Decimal("50"), high=Decimal("52"))
        status, distance = zone_status(Decimal("51"), zone)
        assert status == "in_zone"
        assert distance is None

    def test_bounds_are_inclusive(self):
        zone = EntryZone(tier="t", low=Decimal("50"), high=Decimal("52"))
        assert zone_status(Decimal("50"), zone)[0] == "in_zone"
        assert zone_status(Decimal("52"), zone)[0] == "in_zone"

    def test_approaching_from_above(self):
        zone = EntryZone(tier="t", low=Decimal("50"), high=Decimal("52"))
        status, distance = zone_status(Decimal("53"), zone)
        assert status == "approaching"
        # (52 - 53) / 53 * 100 = -1.89: price must fall 1.89% to enter
        assert distance == Decimal("-1.89")

    def test_above_beyond_three_percent(self):
        zone = EntryZone(tier="t", low=Decimal("50"), high=Decimal("52"))
        status, distance = zone_status(Decimal("60"), zone)
        assert status == "above"
        assert distance < Decimal("-3")

    def test_below_the_zone(self):
        zone = EntryZone(tier="t", low=Decimal("50"), high=Decimal("52"))
        status, distance = zone_status(Decimal("47"), zone)
        assert status == "below"
        # Distance points at the entry edge (the high)
        assert distance > 0

    def test_high_only_zone(self):
        zone = EntryZone(tier="sub-46", low=None, high=Decimal("46"))
        assert zone_status(Decimal("45"), zone)[0] == "in_zone"
        assert zone_status(Decimal("46.5"), zone)[0] == "approaching"
        assert zone_status(Decimal("60"), zone)[0] == "above"

    def test_low_only_zone(self):
        zone = EntryZone(tier="breakout", low=Decimal("230"), high=None)
        assert zone_status(Decimal("240"), zone)[0] == "in_zone"
        # Below the low, within 3% of entering from below
        assert zone_status(Decimal("228"), zone)[0] == "approaching"
        assert zone_status(Decimal("200"), zone)[0] == "below"

    def test_build_statuses_without_price(self):
        statuses = build_zone_statuses(None, parse_zones(EQT_ZONES))
        assert [s.status for s in statuses] == ["unknown"] * 3
        assert all(s.distance_percent is None for s in statuses)

    def test_build_statuses_with_price(self):
        # 47.0: below tier 1, on tier 2's low bound, 2.1% above tier 3's edge
        statuses = build_zone_statuses(Decimal("47.0"), parse_zones(EQT_ZONES))
        by_tier = {s.tier: s.status for s in statuses}
        assert by_tier == {
            "Half starter": "below",
            "Full add": "in_zone",
            "Aggressive": "approaching",
        }


class TestEntryZoneValidation:
    def test_zone_requires_a_bound(self):
        with pytest.raises(ValidationError):
            EntryZone(tier="t", low=None, high=None)

    def test_low_must_be_less_than_high(self):
        with pytest.raises(ValidationError):
            EntryZone(tier="t", low=Decimal("52"), high=Decimal("50"))

    def test_duplicate_tier_names_rejected(self):
        with pytest.raises(ValidationError):
            WatchlistItemUpdate(
                entry_zones=[
                    {"tier": "t", "low": "50", "high": "52"},
                    {"tier": "t", "low": "47", "high": "48"},
                ]
            )

    def test_too_many_zones_rejected(self):
        with pytest.raises(ValidationError):
            WatchlistItemUpdate(
                entry_zones=[
                    {"tier": f"t{i}", "low": str(i), "high": str(i + 1)}
                    for i in range(9)
                ]
            )


# ---------------------------------------------------------------------------
# Zone-hit alert: per-tier firing + dedup
# ---------------------------------------------------------------------------

class TestZoneAlertProcessing:
    @patch("app.services.alert.discord_service")
    async def test_baseline_then_tiered_descent_fires_each_tier_once(
        self, mock_discord, db: AsyncSession
    ):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity, item = await _zone_item(db, symbol="ZA1")
        from tests.factories import create_test_alert
        alert = await create_test_alert(
            db, equity,
            name="EQT entry zones",
            condition_type="entry_zone",
            threshold_value=0,
            watchlist_item_id=item.id,
        )

        # First check at 52.61: baseline, everything arms, nothing fires
        fired, error = await _zone_service(db, 52.61).process_alert(alert)
        assert error is None
        assert fired is False
        assert all(s["armed"] for s in alert.zone_state.values())

        # Price enters tier 1 -> fires once
        fired, _ = await _zone_service(db, 51.0).process_alert(alert)
        assert fired is True
        assert alert.zone_state["Half starter"]["armed"] is False
        assert mock_discord.send_alert_notification.await_count == 1
        call = mock_discord.send_alert_notification.await_args.kwargs
        assert "Half starter" in call["alert_name"]

        # Still in tier 1 -> no re-fire
        fired, _ = await _zone_service(db, 50.5).process_alert(alert)
        assert fired is False
        assert mock_discord.send_alert_notification.await_count == 1

        # Drops into tier 2 -> tier 2 fires, tier 1 does NOT re-fire
        fired, _ = await _zone_service(db, 47.5).process_alert(alert)
        assert fired is True
        assert mock_discord.send_alert_notification.await_count == 2
        call = mock_discord.send_alert_notification.await_args.kwargs
        assert "Full add" in call["alert_name"]
        assert alert.zone_state["Half starter"]["armed"] is False

        # Recovers back into tier 1 from below -> same excursion, no fire
        fired, _ = await _zone_service(db, 51.0).process_alert(alert)
        assert fired is False
        assert mock_discord.send_alert_notification.await_count == 2

    @patch("app.services.alert.discord_service")
    async def test_rearms_after_exit_out_the_entry_side(
        self, mock_discord, db: AsyncSession
    ):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity, item = await _zone_item(db, symbol="ZA2")
        from tests.factories import create_test_alert
        alert = await create_test_alert(
            db, equity,
            condition_type="entry_zone",
            threshold_value=0,
            watchlist_item_id=item.id,
            cooldown_minutes=1,
        )

        await _zone_service(db, 55.0).process_alert(alert)   # baseline
        fired, _ = await _zone_service(db, 51.0).process_alert(alert)
        assert fired is True

        # Exit above the zone -> re-arms; cooldown must also have passed
        await _zone_service(db, 53.0).process_alert(alert)
        assert alert.zone_state["Half starter"]["armed"] is True
        alert.zone_state = {
            **alert.zone_state,
            "Half starter": {
                **alert.zone_state["Half starter"],
                "last_fired_at": (
                    datetime.now(timezone.utc) - timedelta(minutes=5)
                ).isoformat(),
            },
        }

        fired, _ = await _zone_service(db, 51.5).process_alert(alert)
        assert fired is True
        assert mock_discord.send_alert_notification.await_count == 2

    @patch("app.services.alert.discord_service")
    async def test_per_tier_cooldown_blocks_refire_within_window(
        self, mock_discord, db: AsyncSession
    ):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity, item = await _zone_item(db, symbol="ZA3")
        from tests.factories import create_test_alert
        alert = await create_test_alert(
            db, equity,
            condition_type="entry_zone",
            threshold_value=0,
            watchlist_item_id=item.id,
            cooldown_minutes=60,
        )

        await _zone_service(db, 55.0).process_alert(alert)   # baseline
        fired, _ = await _zone_service(db, 51.0).process_alert(alert)
        assert fired is True

        # Whipsaw: exits above (re-arms) and re-enters inside the cooldown
        await _zone_service(db, 53.0).process_alert(alert)
        fired, _ = await _zone_service(db, 51.0).process_alert(alert)
        assert fired is False
        assert mock_discord.send_alert_notification.await_count == 1

    @patch("app.services.alert.discord_service")
    async def test_baseline_inside_zone_does_not_fire(
        self, mock_discord, db: AsyncSession
    ):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity, item = await _zone_item(db, symbol="ZA4")
        from tests.factories import create_test_alert
        alert = await create_test_alert(
            db, equity,
            condition_type="entry_zone",
            threshold_value=0,
            watchlist_item_id=item.id,
        )

        fired, _ = await _zone_service(db, 51.0).process_alert(alert)
        assert fired is False
        assert alert.zone_state["Half starter"]["armed"] is False
        # The other tiers (not entered) arm normally
        assert alert.zone_state["Full add"]["armed"] is True

    @patch("app.services.alert.discord_service")
    async def test_gap_through_to_deep_tier_then_recovery(
        self, mock_discord, db: AsyncSession
    ):
        """A gap to tier 3 fires only tier 3; recovery into tier 2 fires it."""
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity, item = await _zone_item(db, symbol="ZA5")
        from tests.factories import create_test_alert
        alert = await create_test_alert(
            db, equity,
            condition_type="entry_zone",
            threshold_value=0,
            watchlist_item_id=item.id,
        )

        await _zone_service(db, 55.0).process_alert(alert)   # baseline
        fired, _ = await _zone_service(db, 45.0).process_alert(alert)
        assert fired is True
        assert mock_discord.send_alert_notification.await_count == 1
        call = mock_discord.send_alert_notification.await_args.kwargs
        assert "Aggressive" in call["alert_name"]

        # Recovery up into tier 2: a fresh entry for that tier
        fired, _ = await _zone_service(db, 47.5).process_alert(alert)
        assert fired is True
        call = mock_discord.send_alert_notification.await_args.kwargs
        assert "Full add" in call["alert_name"]

    @patch("app.services.alert.discord_service")
    async def test_fetch_failure_preserves_zone_state(
        self, mock_discord, db: AsyncSession
    ):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity, item = await _zone_item(db, symbol="ZA6")
        from tests.factories import create_test_alert
        alert = await create_test_alert(
            db, equity,
            condition_type="entry_zone",
            threshold_value=0,
            watchlist_item_id=item.id,
        )

        await _zone_service(db, 51.0).process_alert(alert)
        state_before = dict(alert.zone_state)

        fired, error = await _zone_service(db, None).process_alert(alert)
        assert fired is False
        assert error is None
        assert alert.zone_state == state_before

    @patch("app.services.alert.discord_service")
    async def test_zone_edits_reconcile_state(self, mock_discord, db: AsyncSession):
        """Removed tiers drop out of state; new tiers baseline without firing."""
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity, item = await _zone_item(db, symbol="ZA7")
        from tests.factories import create_test_alert
        alert = await create_test_alert(
            db, equity,
            condition_type="entry_zone",
            threshold_value=0,
            watchlist_item_id=item.id,
        )

        await _zone_service(db, 55.0).process_alert(alert)
        assert set(alert.zone_state) == {"Half starter", "Full add", "Aggressive"}

        item.entry_zones = [{"tier": "New band", "low": "53", "high": "56"}]
        await db.flush()

        # Price 55 is inside the new band, but first sight = baseline, no fire
        fired, _ = await _zone_service(db, 55.0).process_alert(alert)
        assert fired is False
        assert set(alert.zone_state) == {"New band"}
        assert alert.zone_state["New band"]["armed"] is False

    @patch("app.services.alert.discord_service")
    async def test_no_zones_is_a_noop(self, mock_discord, db: AsyncSession):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity, item = await _zone_item(db, symbol="ZA8", zones=[])
        from tests.factories import create_test_alert
        alert = await create_test_alert(
            db, equity,
            condition_type="entry_zone",
            threshold_value=0,
            watchlist_item_id=item.id,
        )

        fired, error = await _zone_service(db, 51.0).process_alert(alert)
        assert fired is False
        assert error is None
        assert alert.zone_state is None

    @patch("app.services.alert.discord_service")
    async def test_history_records_zone_edge_as_threshold(
        self, mock_discord, db: AsyncSession
    ):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity, item = await _zone_item(db, symbol="ZA9")
        from tests.factories import create_test_alert
        alert = await create_test_alert(
            db, equity,
            condition_type="entry_zone",
            threshold_value=0,
            watchlist_item_id=item.id,
        )

        await _zone_service(db, 55.0).process_alert(alert)
        await _zone_service(db, 51.0).process_alert(alert)

        service = AlertService(db)
        history = await service.get_alert_history(alert.id)
        assert len(history) == 1
        # The tier's entry edge (the high bound), not the stored 0
        assert history[0].threshold_value == Decimal("52")
        assert history[0].triggered_value == Decimal("51")


# ---------------------------------------------------------------------------
# Alert CRUD for entry_zone condition
# ---------------------------------------------------------------------------

class TestZoneAlertCrud:
    async def test_create_resolves_equity_from_item(self, db: AsyncSession):
        from tests.factories import create_test_user

        equity, item = await _zone_item(db, symbol="ZC1")
        owner = await create_test_user(db, email="zone-owner-1@example.com")
        service = AlertService(db, owner.id)

        created = await service.create_alert(
            AlertCreate(
                name="zones",
                condition_type=AlertConditionType.ENTRY_ZONE,
                watchlist_item_id=item.id,
            )
        )
        assert created.watchlist_item_id == item.id
        assert created.equity_id == equity.id
        assert created.threshold_value == Decimal("0")
        assert created.target is not None
        assert created.target.symbol == "ZC1"

    async def test_create_unknown_item_rejected(self, db: AsyncSession):
        from tests.factories import create_test_user

        owner = await create_test_user(db, email="zone-owner-2@example.com")
        service = AlertService(db, owner.id)
        with pytest.raises(ValueError, match="not found"):
            await service.create_alert(
                AlertCreate(
                    name="zones",
                    condition_type=AlertConditionType.ENTRY_ZONE,
                    watchlist_item_id=999999,
                )
            )

    def test_schema_requires_watchlist_item(self):
        with pytest.raises(ValidationError, match="watchlist_item_id"):
            AlertCreate(name="z", condition_type=AlertConditionType.ENTRY_ZONE)

    def test_schema_rejects_symbol_with_entry_zone(self):
        with pytest.raises(ValidationError):
            AlertCreate(
                name="z",
                condition_type=AlertConditionType.ENTRY_ZONE,
                watchlist_item_id=1,
                equity_symbol="EQT",
            )

    def test_schema_rejects_item_id_for_other_conditions(self):
        with pytest.raises(ValidationError):
            AlertCreate(
                name="z",
                condition_type=AlertConditionType.BELOW,
                threshold_value=Decimal("50"),
                equity_symbol="EQT",
                watchlist_item_id=1,
            )

    def test_schema_still_requires_threshold_for_other_conditions(self):
        with pytest.raises(ValidationError, match="threshold_value"):
            AlertCreate(
                name="z",
                condition_type=AlertConditionType.BELOW,
                equity_symbol="EQT",
            )

    def test_update_schema_rejects_entry_zone(self):
        with pytest.raises(ValidationError):
            AlertUpdate(condition_type=AlertConditionType.ENTRY_ZONE)

    async def test_update_cannot_change_condition_away(self, db: AsyncSession):
        equity, item = await _zone_item(db, symbol="ZC2")
        from tests.factories import create_test_alert
        alert = await create_test_alert(
            db, equity,
            condition_type="entry_zone",
            threshold_value=0,
            watchlist_item_id=item.id,
        )
        service = AlertService(db)
        with pytest.raises(ValueError, match="entry_zone"):
            await service.update_alert(
                alert.id,
                AlertUpdate(
                    condition_type=AlertConditionType.BELOW,
                    threshold_value=Decimal("50"),
                ),
            )


# ---------------------------------------------------------------------------
# Watchlist item zones CRUD
# ---------------------------------------------------------------------------

class TestWatchlistZonesCrud:
    def _service(self, db, price: float | None = 51.0) -> WatchlistService:
        service = WatchlistService(db)
        service.equity_service.get_quote = AsyncMock(
            return_value=_quote(price) if price is not None else None
        )
        return service

    async def test_add_item_with_zones(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="WZ1")
        wl = await create_test_watchlist(db, name="WZ1 list")
        service = self._service(db)

        item = await service.add_item(
            wl.id,
            WatchlistItemCreate(
                equity_id=equity.id,
                entry_zones=[EntryZone(tier="Half starter", low=Decimal("50"), high=Decimal("52"))],
            ),
        )
        assert item is not None
        assert len(item.entry_zones) == 1
        assert item.entry_zones[0].tier == "Half starter"
        # Quote at 51 -> in zone
        assert item.zone_statuses[0].status == "in_zone"

    async def test_update_sets_and_clears_zones(self, db: AsyncSession):
        equity, item = await _zone_item(db, symbol="WZ2")
        service = self._service(db, price=241.0)

        # Omitted entry_zones leaves them unchanged
        updated = await service.update_item(
            item.watchlist_id, item.id, WatchlistItemUpdate(notes="note")
        )
        assert len(updated.entry_zones) == 3

        # Explicit null clears
        updated = await service.update_item(
            item.watchlist_id, item.id, WatchlistItemUpdate(entry_zones=None)
        )
        assert updated.entry_zones == []
        assert updated.zone_statuses == []

    async def test_update_replaces_zones(self, db: AsyncSession):
        equity, item = await _zone_item(db, symbol="WZ3")
        service = self._service(db, price=232.0)

        updated = await service.update_item(
            item.watchlist_id,
            item.id,
            WatchlistItemUpdate(
                entry_zones=[
                    EntryZone(tier="Taxable add", low=Decimal("230"), high=Decimal("235"))
                ]
            ),
        )
        assert [z.tier for z in updated.entry_zones] == ["Taxable add"]
        assert updated.zone_statuses[0].status == "in_zone"

    async def test_statuses_unknown_without_quote(self, db: AsyncSession):
        equity, item = await _zone_item(db, symbol="WZ4")
        service = self._service(db, price=None)

        wl = await service.get_watchlist(item.watchlist_id, include_quotes=True)
        statuses = wl.items[0].zone_statuses
        assert len(statuses) == 3
        assert all(s.status == "unknown" for s in statuses)
