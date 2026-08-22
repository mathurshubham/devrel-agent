"""Shared FastAPI dependency for the process-wide async Redis client.

FastAPI (uvicorn) runs one long-lived event loop for the life of the
process, so a module-level client is safe here -- unlike Celery task bodies,
which each get their own ``asyncio.run()`` event loop and need a fresh
client per invocation (see ``backend.utils.celery_async``).

Routed through a dependency (rather than importing the module-level client
directly, as ``backend/api/org.py`` does) so router tests can override it
with a fake client the same way they override ``get_db``/``get_current_session``
-- see ``tests/api/test_analytics_router.py``.
"""
import os

import redis.asyncio as redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
_redis_client = redis.from_url(REDIS_URL)


async def get_redis() -> redis.Redis:
    return _redis_client
