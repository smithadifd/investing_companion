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
    # --- Delivery reliability (alert outbox) ---
    # acks_late + reject_on_worker_lost: a task is only acked AFTER it finishes,
    # so a worker crash mid-run re-queues the message instead of dropping it.
    # Safe here because alert delivery is idempotent at the outbox layer (per-
    # row lease + unique idempotency key), so a redelivered task cannot double-
    # send.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # visibility_timeout must exceed the delivery lease so a redelivered task
    # does not race a still-leased row.
    broker_transport_options={"visibility_timeout": 600},
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
        # Drain the alert-delivery outbox every 30s: claim pending rows (lease
        # + bounded retry) and send them. Decoupled from evaluation so a send
        # failure never rolls back the trigger record.
        "deliver-pending-alerts": {
            "task": "alerts.deliver_pending_notifications",
            "schedule": 30.0,
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
        # Persist daily OHLCV bars after market close. Percent-change and
        # percent-from-high alerts read their reference values from this data.
        "sync-price-history-daily": {
            "task": "price_history.sync_all",
            "schedule": crontab(hour=21, minute=15),
        },
        # Nudge on Discord as the Schwab refresh token nears its 7-day expiry.
        # Daily at 13:00 UTC (~9 AM ET) so reconnect reminders land in the morning.
        "check-schwab-token-expiry-daily": {
            "task": "schwab.check_token_expiry",
            "schedule": crontab(hour=13, minute=0),
        },
    }

# Auto-discover tasks from these modules
celery_app.autodiscover_tasks(["app.tasks"])
