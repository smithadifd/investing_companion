"""Every task Celery Beat schedules must be registered on the worker.

``autodiscover_tasks(["app.tasks"])`` only finds a module named ``tasks``, so a
task module is registered only when ``app/tasks/__init__.py`` imports it. A
module left out is silently dropped: Beat keeps sending its task and the worker
rejects it as unregistered.
"""

import app.tasks  # noqa: F401  (registers tasks the way the worker does)
from app.tasks.celery_app import celery_app


def test_every_beat_scheduled_task_is_registered():
    scheduled = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    missing = sorted(scheduled - set(celery_app.tasks.keys()))
    assert not missing, f"scheduled but unregistered: {missing}"


def test_event_refresh_tasks_are_registered():
    for name in (
        "events.refresh_all_watchlist_events",
        "events.refresh_macro_calendar",
        "events.refresh_equity_events",
        "events.refresh_user_watchlist_events",
    ):
        assert name in celery_app.tasks
