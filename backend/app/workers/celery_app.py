"""Celery application and beat schedule."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "leadgen",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,                 # a killed worker re-runs the task
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,        # long tasks must not hog the queue
    task_time_limit=60 * 30,
    task_soft_time_limit=60 * 25,
    result_expires=60 * 60 * 24 * 3,
    broker_connection_retry_on_startup=True,
    task_default_retry_delay=60,
    task_annotations={"*": {"max_retries": 3}},
)

celery_app.conf.beat_schedule = {
    # The outreach loop runs often; the throttle decides whether anything goes out.
    "outreach-batch": {
        "task": "leadgen.outreach_batch",
        "schedule": crontab(minute="*/5"),
        "kwargs": {"limit": 25},
    },
    "poll-inbox": {
        "task": "leadgen.poll_inbox",
        "schedule": float(settings.imap_poll_seconds),
    },
    "qualify-businesses": {
        "task": "leadgen.qualify_pending",
        "schedule": crontab(minute="*/10"),
        "kwargs": {"limit": 50},
    },
    "rollup-stats": {
        "task": "leadgen.rollup_stats",
        "schedule": crontab(minute="*/15"),
    },
    "daily-digest": {
        "task": "leadgen.daily_digest",
        "schedule": crontab(hour=settings.telegram_daily_digest_hour, minute=5),
    },
    "retention-sweep": {
        "task": "leadgen.retention_sweep",
        "schedule": crontab(hour=3, minute=30),
    },
}
