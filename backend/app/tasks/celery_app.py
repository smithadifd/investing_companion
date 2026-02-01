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
    # Send daily summary at 6 PM UTC
    "send-daily-summary": {
        "task": "alerts.send_daily_summary",
        "schedule": crontab(hour=18, minute=0),
    },
}

# Auto-discover tasks from these modules
celery_app.autodiscover_tasks(["app.tasks"])
