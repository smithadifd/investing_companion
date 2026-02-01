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
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
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
}
