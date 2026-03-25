"""Celery application configuration."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "investing_companion",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    worker_prefetch_multiplier=1,
    result_expires=3600,  # 1 hour
)

# Celery Beat schedule for periodic tasks
# In demo mode: disable alerts and notifications (no webhook configured),
# but keep event refresh so calendar data stays current
if settings.DEMO_MODE:
    celery_app.conf.beat_schedule = {
        "refresh-watchlist-events-daily": {
            "task": "events.refresh_all_watchlist_events",
            "schedule": crontab(hour=22, minute=0),
        },
    }
else:
    celery_app.conf.beat_schedule = {
        # Check all active alerts every 5 minutes
        "check-alerts-every-5-minutes": {
            "task": "alerts.check_all_alerts",
            "schedule": 300.0,  # 5 minutes in seconds
        },
        # Dynamic notification scheduler - checks configured send times every minute
        # Fires morning pulse and EOD wrap tasks when the time matches settings
        "check-notification-schedule": {
            "task": "alerts.check_notification_schedule",
            "schedule": 60.0,  # Every minute
        },
        # Refresh earnings/dividend events daily at 5 PM ET (10 PM UTC)
        # Runs after market close to get updated earnings dates
        "refresh-watchlist-events-daily": {
            "task": "events.refresh_all_watchlist_events",
            "schedule": crontab(hour=22, minute=0),
        },
    }

# Auto-discover tasks from these modules
celery_app.autodiscover_tasks(["app.tasks"])
