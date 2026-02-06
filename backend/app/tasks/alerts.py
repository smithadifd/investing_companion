"""Celery tasks for alert monitoring and notifications."""

import asyncio
import logging
from datetime import datetime, timezone

from app.db.session import AsyncSessionLocal
from app.services.alert import AlertService
from app.services.notifications.discord import discord_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async code in sync Celery task."""
    from app.db.session import engine

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        # Close the Discord httpx client before the loop is destroyed,
        # otherwise it tries to close its socket on a dead loop next time.
        loop.run_until_complete(discord_service.close())
        # Dispose the engine to close all pooled connections.
        # Without this, asyncpg connections are orphaned when the
        # event loop is destroyed, causing "idle in transaction" leaks.
        loop.run_until_complete(engine.dispose())
        loop.close()


@celery_app.task(name="alerts.check_all_alerts")
def check_all_alerts():
    """
    Check all active alerts and send notifications for triggered ones.

    This task is scheduled to run periodically via Celery Beat.
    """
    logger.info("Starting alert check task")

    async def _check():
        async with AsyncSessionLocal() as session:
            service = AlertService(session)
            result = await service.check_all_active_alerts()
            return result

    try:
        result = run_async(_check())
        logger.info(
            f"Alert check complete: {result['checked']} checked, "
            f"{result['triggered']} triggered, {result['errors']} errors"
        )
        return result
    except Exception as e:
        logger.error(f"Error in alert check task: {e}", exc_info=True)
        raise


@celery_app.task(name="alerts.check_single_alert")
def check_single_alert(alert_id: int):
    """
    Check a single alert by ID.

    Useful for on-demand checking or testing.
    """
    logger.info(f"Checking single alert: {alert_id}")

    async def _check():
        from sqlalchemy import select
        from app.db.models.alert import Alert

        async with AsyncSessionLocal() as session:
            service = AlertService(session)
            stmt = select(Alert).where(Alert.id == alert_id)
            result = await session.execute(stmt)
            alert = result.scalar_one_or_none()

            if not alert:
                return {"error": f"Alert {alert_id} not found"}

            was_triggered, error = await service.process_alert(alert)
            return {
                "alert_id": alert_id,
                "triggered": was_triggered,
                "error": error,
            }

    try:
        result = run_async(_check())
        logger.info(f"Single alert check result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error checking alert {alert_id}: {e}", exc_info=True)
        raise


@celery_app.task(name="alerts.send_morning_pulse")
def send_morning_pulse():
    """Send morning pulse notification with futures, overnight moves, calendar, and movers."""
    logger.info("Sending morning pulse notification")

    async def _send():
        from datetime import timedelta

        from sqlalchemy import func, select

        from app.db.models.alert import Alert, AlertHistory
        from app.services.data_providers.yahoo import YahooFinanceProvider
        from app.services.economic_event import EconomicEventService
        from app.services.notifications.formatters import MorningData, format_morning_pulse
        from app.services.watchlist import WatchlistService

        yahoo = YahooFinanceProvider()

        async with AsyncSessionLocal() as session:
            # --- Futures ---
            futures_data: dict[str, dict] = {}
            for symbol in ("ES=F", "NQ=F", "RTY=F"):
                try:
                    q = await yahoo.get_quote(symbol)
                    if q and q.change_percent is not None:
                        futures_data[symbol] = {
                            "price": float(q.price),
                            "change_percent": float(q.change_percent),
                        }
                except Exception as e:
                    logger.warning(f"Failed to fetch {symbol}: {e}")

            # --- VIX and 10Y ---
            vix_data: dict = {}
            ten_year_data: dict = {}
            try:
                q = await yahoo.get_quote("^VIX")
                if q:
                    vix_data = {"price": float(q.price), "change": float(q.change or 0)}
            except Exception as e:
                logger.warning(f"Failed to fetch VIX: {e}")
            try:
                q = await yahoo.get_quote("^TNX")
                if q:
                    ten_year_data = {"price": float(q.price), "change": float(q.change or 0)}
            except Exception as e:
                logger.warning(f"Failed to fetch 10Y: {e}")

            # --- Overnight moves ---
            overnight_symbols = [
                ("GC=F", "Gold"),
                ("SI=F", "Silver"),
                ("DX-Y.NYB", "Dollar (DXY)"),
                ("CL=F", "Crude"),
                ("NG=F", "Nat Gas"),
                ("VEA", "VEA"),
                ("VWO", "VWO"),
            ]
            overnight_moves: list[dict] = []
            for symbol, name in overnight_symbols:
                try:
                    q = await yahoo.get_quote(symbol)
                    if q and q.change_percent is not None:
                        overnight_moves.append({
                            "name": name,
                            "symbol": symbol,
                            "change_percent": float(q.change_percent),
                            "price": float(q.price),
                        })
                except Exception as e:
                    logger.warning(f"Failed to fetch {symbol}: {e}")

            # --- Today's calendar events ---
            event_service = EconomicEventService(session)
            today_result = await event_service.get_upcoming_events(
                days_ahead=1, user_id=None, limit=15,
            )
            calendar_events = [
                {
                    "event_time": e.event_time,
                    "title": e.title,
                    "importance": e.importance.value if e.importance else "medium",
                    "event_type": e.event_type.value if e.event_type else "",
                    "symbol": e.equity.symbol if e.equity else None,
                }
                for e in today_result.events
                if (e.importance and e.importance.value in ("medium", "high"))
            ]

            # --- Pre-market movers from watchlists ---
            watchlist_service = WatchlistService(session)
            all_watchlists = await watchlist_service.list_watchlists()
            premarket_movers: list[dict] = []
            seen_symbols: set[str] = set()
            for wl_summary in all_watchlists:
                wl = await watchlist_service.get_watchlist(wl_summary.id, include_quotes=True)
                if not wl:
                    continue
                for item in wl.items:
                    sym = item.equity.symbol
                    if sym in seen_symbols:
                        continue
                    seen_symbols.add(sym)
                    if item.quote and item.quote.change_percent is not None:
                        change_pct = float(item.quote.change_percent)
                        if abs(change_pct) >= 2.0:
                            premarket_movers.append({
                                "symbol": sym,
                                "change_percent": change_pct,
                            })
            premarket_movers.sort(key=lambda m: abs(m["change_percent"]), reverse=True)

            # --- Alert stats ---
            active_count = await session.scalar(
                select(func.count(Alert.id)).where(Alert.is_active == True)  # noqa: E712
            ) or 0
            # Triggered since previous close (21:30 UTC yesterday = 4:30 PM ET)
            yesterday_close = (
                datetime.now(timezone.utc).replace(hour=21, minute=30, second=0, microsecond=0)
                - timedelta(days=1)
            )
            triggered_overnight = await session.scalar(
                select(func.count(AlertHistory.id)).where(
                    AlertHistory.triggered_at >= yesterday_close
                )
            ) or 0

            # --- Build and send ---
            data = MorningData(
                futures=futures_data,
                vix=vix_data,
                ten_year=ten_year_data,
                overnight_moves=overnight_moves,
                calendar_events=calendar_events,
                premarket_movers=premarket_movers,
                active_alerts=active_count,
                triggered_overnight=triggered_overnight,
            )
            message = format_morning_pulse(data)
            success, error = await discord_service.send_plain_text(message)
            return {"success": success, "error": error, "length": len(message)}

    try:
        result = run_async(_send())
        logger.info(f"Morning pulse result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error sending morning pulse: {e}", exc_info=True)
        raise


@celery_app.task(name="alerts.send_eod_wrap")
def send_eod_wrap():
    """Send end-of-day wrap with market close, themes, positions, movers, alerts, tomorrow."""
    logger.info("Sending EOD wrap notification")

    async def _send():
        from datetime import date, timedelta

        from sqlalchemy import func, select
        from sqlalchemy.orm import selectinload

        from app.db.models.alert import Alert, AlertHistory
        from app.schemas.economic_event import EventFilters
        from app.services.data_providers.yahoo import YahooFinanceProvider
        from app.services.economic_event import EconomicEventService
        from app.services.notifications.formatters import (
            AlertTrigger,
            EODData,
            ThemeData,
            format_eod_wrap,
            get_theme_emoji,
        )
        from app.services.watchlist import WatchlistService

        yahoo = YahooFinanceProvider()

        async with AsyncSessionLocal() as session:
            # --- Market close data ---
            market_data: dict[str, dict] = {}
            for symbol in ("SPY", "QQQ", "IWM", "^VIX", "^TNX", "DX-Y.NYB"):
                try:
                    q = await yahoo.get_quote(symbol)
                    if q:
                        market_data[symbol] = {
                            "price": float(q.price),
                            "change_percent": float(q.change_percent) if q.change_percent else 0,
                        }
                except Exception as e:
                    logger.warning(f"Failed to fetch {symbol}: {e}")

            # --- Theme performance + My positions ---
            watchlist_service = WatchlistService(session)
            all_watchlists = await watchlist_service.list_watchlists()
            themes: list[ThemeData] = []
            my_positions: list[dict] = []
            all_movers: list[dict] = []  # for big movers section

            for wl_summary in all_watchlists:
                wl = await watchlist_service.get_watchlist(wl_summary.id, include_quotes=True)
                if not wl:
                    continue

                positions = []
                for item in wl.items:
                    if item.quote and item.quote.change_percent is not None:
                        pos = {
                            "symbol": item.equity.symbol,
                            "change_percent": float(item.quote.change_percent),
                        }
                        positions.append(pos)
                        all_movers.append(pos)

                if wl.is_default:
                    # This is "My Positions"
                    my_positions = positions
                elif positions:
                    themes.append(ThemeData(
                        name=wl.name,
                        emoji=get_theme_emoji(wl.name),
                        positions=positions,
                    ))

            # --- Alert data ---
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            active_count = await session.scalar(
                select(func.count(Alert.id)).where(Alert.is_active == True)  # noqa: E712
            ) or 0

            # Get triggered alerts today with details
            stmt = (
                select(AlertHistory)
                .options(selectinload(AlertHistory.alert).selectinload(Alert.equity))
                .where(AlertHistory.triggered_at >= today_start)
                .order_by(AlertHistory.triggered_at.desc())
                .limit(5)
            )
            result = await session.execute(stmt)
            triggered_rows = result.scalars().all()

            alerts_triggered: list[AlertTrigger] = []
            for h in triggered_rows:
                alert = h.alert
                symbol = alert.equity.symbol if alert.equity else (
                    alert.ratio.name if alert.ratio else "?"
                )
                cond = alert.condition_type
                threshold = float(h.threshold_value)
                if "below" in cond or "down" in cond:
                    name = f"{symbol} < {threshold:.2f}"
                else:
                    name = f"{symbol} > {threshold:.2f}"
                alerts_triggered.append(AlertTrigger(
                    name=name,
                    triggered_value=float(h.triggered_value),
                ))

            # --- Tomorrow's calendar ---
            event_service = EconomicEventService(session)
            tomorrow = date.today() + timedelta(days=1)
            # Skip weekends
            if tomorrow.weekday() == 5:  # Saturday
                tomorrow += timedelta(days=2)
            elif tomorrow.weekday() == 6:  # Sunday
                tomorrow += timedelta(days=1)

            filters = EventFilters(
                start_date=tomorrow,
                end_date=tomorrow,
                include_past=False,
            )
            tomorrow_events_raw = await event_service.list_events(
                filters=filters, user_id=None, limit=10,
            )
            tomorrow_events = [
                {
                    "event_time": e.event_time,
                    "title": e.title,
                    "importance": e.importance.value if e.importance else "medium",
                    "event_type": e.event_type.value if e.event_type else "",
                    "symbol": e.equity.symbol if e.equity else None,
                }
                for e in tomorrow_events_raw
                if (e.importance and e.importance.value in ("medium", "high"))
            ]

            # --- Build and send ---
            data = EODData(
                market=market_data,
                themes=themes,
                my_positions=my_positions,
                big_movers=all_movers,
                alerts_triggered=alerts_triggered,
                active_alerts=active_count,
                tomorrow_events=tomorrow_events,
            )
            message = format_eod_wrap(data)
            success, error = await discord_service.send_plain_text(message)
            return {"success": success, "error": error, "length": len(message)}

    try:
        result = run_async(_send())
        logger.info(f"EOD wrap result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error sending EOD wrap: {e}", exc_info=True)
        raise


@celery_app.task(name="alerts.check_notification_schedule")
def check_notification_schedule():
    """Check if it's time to send morning or EOD notifications.

    Runs every minute.  Reads configured send times from user settings,
    compares to current time, and fires the appropriate task if matched.
    Uses a "last sent date" key to prevent double-sends.
    """
    from zoneinfo import ZoneInfo

    async def _check():
        from app.services.settings import SettingsService

        ET = ZoneInfo("America/New_York")
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(ET)

        # Skip weekends
        if now_et.weekday() >= 5:
            return {"skipped": "weekend"}

        current_hhmm = now_et.strftime("%H:%M")
        today_str = now_et.strftime("%Y-%m-%d")

        async with AsyncSessionLocal() as session:
            svc = SettingsService(session)
            morning_time = await svc.get_setting(svc.MORNING_NOTIFICATION_TIME) or "08:00"
            eod_time = await svc.get_setting(svc.EOD_NOTIFICATION_TIME) or "16:30"

            morning_last = await svc.get_setting(svc.MORNING_NOTIFICATION_LAST_SENT) or ""
            eod_last = await svc.get_setting(svc.EOD_NOTIFICATION_LAST_SENT) or ""

            sent: list[str] = []

            if current_hhmm == morning_time and morning_last != today_str:
                logger.info(f"Firing morning pulse at {current_hhmm} ET")
                send_morning_pulse.delay()
                await svc.set_setting(svc.MORNING_NOTIFICATION_LAST_SENT, today_str)
                sent.append("morning")

            if current_hhmm == eod_time and eod_last != today_str:
                logger.info(f"Firing EOD wrap at {current_hhmm} ET")
                send_eod_wrap.delay()
                await svc.set_setting(svc.EOD_NOTIFICATION_LAST_SENT, today_str)
                sent.append("eod")

            return {
                "time_et": current_hhmm,
                "morning_target": morning_time,
                "eod_target": eod_time,
                "sent": sent,
            }

    try:
        result = run_async(_check())
        if result.get("sent"):
            logger.info(f"Notification schedule: {result}")
        return result
    except Exception as e:
        logger.error(f"Error in notification schedule check: {e}", exc_info=True)
        raise
