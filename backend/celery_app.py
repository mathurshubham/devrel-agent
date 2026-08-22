import logging
import os
from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init
from kombu import Queue

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "sentinel",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["backend.tasks.scheduler", "backend.tasks.workers"],
)

celery_app.conf.task_queues = (
    Queue("scraper", routing_key="scraper"),
    Queue("langgen", routing_key="langgen"),
    Queue("maintenance", routing_key="maintenance"),
)

celery_app.conf.task_default_queue = "maintenance"
celery_app.conf.task_routes = {
    "backend.tasks.workers.scraper_task": {"queue": "scraper"},
    "backend.tasks.workers.langgen_task": {"queue": "langgen"},
    "backend.tasks.workers.analyst_task": {"queue": "langgen"},
    "backend.tasks.workers.analyst_weekly_tick": {"queue": "maintenance"},
    "backend.tasks.workers.reap_stale_analyst_runs": {"queue": "maintenance"},
    "backend.tasks.workers.clear_expired_locks": {"queue": "maintenance"},
    "backend.tasks.workers.poll_engagement_outcomes": {"queue": "maintenance"},
    "backend.tasks.workers.purge_old_checkpoints_task": {"queue": "maintenance"},
    "backend.tasks.scheduler.scheduler_tick": {"queue": "maintenance"},
    "backend.tasks.scheduler.purge_old_webhook_events": {"queue": "maintenance"},
}

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "scheduler-tick-60s": {
            "task": "backend.tasks.scheduler.scheduler_tick",
            "schedule": 60.0,
        },
        "clear-locks-5m": {
            "task": "backend.tasks.workers.clear_expired_locks",
            "schedule": 300.0,  # 5 minutes
        },
        "purge-old-webhook-events-daily": {
            "task": "backend.tasks.scheduler.purge_old_webhook_events",
            "schedule": 86400.0,  # 24 hours
        },
        "poll-engagement-outcomes-6h": {
            "task": "backend.tasks.workers.poll_engagement_outcomes",
            "schedule": 21600.0,  # 6 hours
        },
        "purge-old-checkpoints-daily": {
            "task": "backend.tasks.workers.purge_old_checkpoints_task",
            "schedule": 86400.0,  # 24 hours
        },
        "analyst-weekly-monday-6am-utc": {
            "task": "backend.tasks.workers.analyst_weekly_tick",
            "schedule": crontab(hour=6, minute=0, day_of_week=1),  # PRD V7 §5.6
        },
        "reap-stale-analyst-runs-15m": {
            "task": "backend.tasks.workers.reap_stale_analyst_runs",
            "schedule": 900.0,  # 15 minutes
        },
    },
)

@worker_process_init.connect
def _setup_checkpointer_tables(**kwargs):
    """Create the langgraph-checkpoint-postgres tables if they don't exist.

    Runs once per worker process on startup, before any langgen_task can
    invoke graph #1. ``setup()`` is idempotent, so this is safe across
    however many worker processes start concurrently. A Postgres outage at
    worker boot must not crash the worker -- the first real pipeline run
    will surface the same failure loudly instead.
    """
    import asyncio

    from backend.pipeline.graph import setup_checkpointer_tables

    try:
        asyncio.run(setup_checkpointer_tables())
    except Exception:  # noqa: BLE001
        logger.exception("Could not set up langgraph checkpoint tables at worker startup")


if __name__ == "__main__":
    celery_app.start()
