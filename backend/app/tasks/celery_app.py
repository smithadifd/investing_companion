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
celery_app.conf.beat_schedule = {
    # Check all active alerts every 5 minutes
    "check-alerts-every-5-minutes": {
        "task": "alerts.check_all_alerts",
        "schedule": 300.0,  # 5 minutes in seconds
    },
    # End-of-day summary (movers + alert activity) at 4:30 PM ET (9:30 PM UTC)
    "send-end-of-day-summary": {
        "task": "alerts.send_end_of_day_summary",
        "schedule": crontab(hour=21, minute=30),
    },
    # Send morning events notification at 7 AM ET (12 PM UTC) before market open
    "send-morning-events": {
        "task": "alerts.send_morning_events",
        "schedule": crontab(hour=12, minute=0),
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
