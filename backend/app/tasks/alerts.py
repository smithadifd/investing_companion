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


@celery_app.task(name="alerts.send_daily_summary")
def send_daily_summary():
    """
    Send daily summary of alert activity to Discord.

    Scheduled to run once per day.
    """
    logger.info("Sending daily alert summary")

    async def _send():
        from sqlalchemy import func, select
        from datetime import timedelta
        from app.db.models.alert import Alert, AlertHistory

        async with AsyncSessionLocal() as session:
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            # Get stats
            active_count = await session.scalar(
                select(func.count(Alert.id)).where(Alert.is_active == True)
            )
            triggered_today = await session.scalar(
                select(func.count(AlertHistory.id)).where(
                    AlertHistory.triggered_at >= today_start
                )
            )

            # Get top triggered alerts
            top_triggered_stmt = (
                select(
                    Alert.name,
                    Alert.equity_id,
                    Alert.ratio_id,
                    func.count(AlertHistory.id).label("count"),
                )
                .join(AlertHistory)
                .where(AlertHistory.triggered_at >= today_start)
                .group_by(Alert.id)
                .order_by(func.count(AlertHistory.id).desc())
                .limit(5)
            )
            top_result = await session.execute(top_triggered_stmt)
            top_triggers = [
                {
                    "name": r[0],
                    "symbol": "N/A",  # Would need to join for full info
                    "count": r[3],
                }
                for r in top_result.all()
            ]

            success, error = await discord_service.send_daily_summary(
                alerts_triggered=triggered_today or 0,
                active_alerts=active_count or 0,
                top_triggers=top_triggers,
            )

            return {"success": success, "error": error}

    try:
        result = run_async(_send())
        logger.info(f"Daily summary result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error sending daily summary: {e}", exc_info=True)
        raise


@celery_app.task(name="alerts.send_daily_movers_summary")
def send_daily_movers_summary(threshold_percent: float = 5.0):
    """
    Send daily summary of watchlist equities that moved more than threshold%.

    Args:
        threshold_percent: Minimum absolute percent change to include (default 5%)

    Scheduled to run once per day after market close.
    """
    logger.info(f"Sending daily movers summary (threshold: {threshold_percent}%)")

    async def _send():
        from app.services.watchlist import WatchlistService

        async with AsyncSessionLocal() as session:
            service = WatchlistService(session)
            # Use the get_all_movers method we created for Issue 008
            movers = await service.get_all_movers(limit=10)

            # Convert Pydantic models to dicts for Discord service
            gainers = [
                {
                    "symbol": g.symbol,
                    "name": g.name,
                    "price": float(g.price),
                    "change_percent": float(g.change_percent),
                    "watchlist_name": g.watchlist_name,
                }
                for g in movers.gainers
            ]
            losers = [
                {
                    "symbol": l.symbol,
                    "name": l.name,
                    "price": float(l.price),
                    "change_percent": float(l.change_percent),
                    "watchlist_name": l.watchlist_name,
                }
                for l in movers.losers
            ]

            success, error = await discord_service.send_movers_summary(
                gainers=gainers,
                losers=losers,
                threshold_percent=threshold_percent,
                total_items=movers.total_items,
                watchlist_count=movers.watchlist_count,
            )

            return {
                "success": success,
                "error": error,
                "gainers_count": len(gainers),
                "losers_count": len(losers),
                "total_items": movers.total_items,
            }

    try:
        result = run_async(_send())
        logger.info(f"Daily movers summary result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error sending daily movers summary: {e}", exc_info=True)
        raise


@celery_app.task(name="alerts.send_morning_events")
def send_morning_events(days_ahead: int = 2):
    """
    Send morning notification of upcoming events for today and tomorrow.

    Args:
        days_ahead: Number of days to look ahead (default 2 for today + tomorrow)

    Scheduled to run each morning before market open.
    """
    logger.info(f"Sending morning events notification (days: {days_ahead})")

    async def _send():
        from app.services.economic_event import EconomicEventService
        from app.schemas.economic_event import EventFilters

        async with AsyncSessionLocal() as session:
            service = EconomicEventService(session)

            # Get upcoming events
            result = await service.get_upcoming_events(
                days_ahead=days_ahead,
                user_id=None,  # System-level, get all events
                limit=30,
            )

            # Convert to dict format for Discord
            events = [
                {
                    "event_date": str(e.event_date),
                    "title": e.title,
                    "event_type": e.event_type,
                    "event_time": e.event_time,
                    "symbol": e.equity.symbol if e.equity else None,
                }
                for e in result.events
            ]

            days_label = "Today" if days_ahead == 1 else f"Next {days_ahead} Days"
            success, error = await discord_service.send_upcoming_events(
                events=events,
                days_label=days_label,
            )

            return {
                "success": success,
                "error": error,
                "events_count": len(events),
            }

    try:
        result = run_async(_send())
        logger.info(f"Morning events result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error sending morning events: {e}", exc_info=True)
        raise


# Celery Beat schedule configuration
# This should be added to celery_app.conf.beat_schedule
ALERT_BEAT_SCHEDULE = {
    "check-alerts-every-5-minutes": {
        "task": "alerts.check_all_alerts",
        "schedule": 300.0,  # 5 minutes
    },
    "send-daily-summary": {
        "task": "alerts.send_daily_summary",
        "schedule": {
            "crontab": {
                "hour": 18,  # 6 PM UTC
                "minute": 0,
            }
        },
    },
    "send-daily-movers-summary": {
        "task": "alerts.send_daily_movers_summary",
        "schedule": {
            "crontab": {
                "hour": 21,  # 9:30 PM UTC = 4:30 PM ET (after market close)
                "minute": 30,
            }
        },
    },
    "send-morning-events": {
        "task": "alerts.send_morning_events",
        "schedule": {
            "crontab": {
                "hour": 12,  # 12 PM UTC = 7 AM ET (before market open)
                "minute": 0,
            }
        },
    },
}
