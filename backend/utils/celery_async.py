"""
Shared helpers for running async code from Celery tasks.

Celery's prefork workers invoke task bodies synchronously, so every task that
needs to await something does `asyncio.run(...)`, which opens a brand new
event loop and closes it again when the coroutine returns. Any client bound
to that loop (an asyncpg connection pool, a redis.asyncio client) cannot
survive past the end of that call -- if one is created at module import time
and reused across separate asyncio.run() invocations, every operation after
the first task run raises "RuntimeError: Event loop is closed".

The fix is structural: never keep a loop-bound client at module scope for
code that runs under asyncio.run(). Build it fresh inside the coroutine,
dispose/close it before the coroutine returns, and use `run_async` below to
run that coroutine. FastAPI does not have this problem -- it runs a single
long-lived event loop for the whole process -- so backend/database.py's
module-level `engine`/`SessionLocal` stays as-is for FastAPI request
handlers; this module is only for Celery task bodies.
"""
import asyncio
import os
from typing import Awaitable, Callable, TypeVar

import redis.asyncio as redis

T = TypeVar("T")


def run_async(coro_fn: Callable[[], Awaitable[T]]) -> T:
    """Run a zero-arg coroutine factory in its own fresh event loop."""
    return asyncio.run(coro_fn())


def new_redis_client() -> redis.Redis:
    """
    Build a fresh redis.asyncio client bound to the current (fresh) event
    loop. Callers must `await client.aclose()` before their coroutine
    returns.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(redis_url)
