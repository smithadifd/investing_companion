"""Celery application configuration."""

from celery import Celery

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

# Auto-discover tasks from these modules
celery_app.autodiscover_tasks(["app.tasks"])
