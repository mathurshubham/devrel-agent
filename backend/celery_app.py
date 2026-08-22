import os
from celery import Celery
from kombu import Queue

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
    "backend.tasks.workers.clear_expired_locks": {"queue": "maintenance"},
    "backend.tasks.workers.poll_engagement_outcomes": {"queue": "maintenance"},
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
    },
)

if __name__ == "__main__":
    celery_app.start()
