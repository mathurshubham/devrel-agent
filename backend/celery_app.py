import os
from celery import Celery
from kombu import Queue

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "sentinel",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.scheduler", "tasks.workers"]
)

celery_app.conf.task_queues = (
    Queue("scraper", routing_key="scraper"),
    Queue("langgen", routing_key="langgen"),
    Queue("praw_publish", routing_key="praw_publish"),
    Queue("maintenance", routing_key="maintenance"),
)

celery_app.conf.task_default_queue = "maintenance"
celery_app.conf.task_routes = {
    "tasks.workers.scraper_task": {"queue": "scraper"},
    "tasks.workers.langgen_task": {"queue": "langgen"},
    "tasks.workers.praw_publish_task": {"queue": "praw_publish"},
    "tasks.workers.praw_delete": {"queue": "praw_publish"},
    "tasks.scheduler.scheduler_tick": {"queue": "maintenance"},
}

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "scheduler-tick-60s": {
            "task": "tasks.scheduler.scheduler_tick",
            "schedule": 60.0,
        },
        "clear-locks-5m": {
            "task": "tasks.workers.clear_expired_locks",
            "schedule": 300.0, # 5 minutes
        },
    },
)

if __name__ == "__main__":
    celery_app.start()
