"""Shared fakes for the pipeline unit tests.

Mirrors the style of ``tests/ingestion/conftest.py``: plain stand-ins for the
async Redis client (extended here with incr/decr for the daily-cap
reservation) rather than a real Redis server.
"""

import pytest


class FakeRedis:
    """Minimal async Redis stand-in covering everything the pipeline touches."""

    def __init__(self, initial=None):
        self.store: dict[str, object] = dict(initial or {})
        self.expirations: dict[str, int] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, **kwargs):
        self.store[key] = value
        if ex:
            self.expirations[key] = ex
        return True

    async def delete(self, key):
        return int(self.store.pop(key, None) is not None)

    async def incr(self, key, amount=1):
        new_val = int(self.store.get(key, 0)) + amount
        self.store[key] = new_val
        return new_val

    async def decr(self, key, amount=1):
        new_val = int(self.store.get(key, 0)) - amount
        self.store[key] = new_val
        return new_val

    async def incrby(self, key, amount):
        return await self.incr(key, amount)

    async def incrbyfloat(self, key, amount):
        total = float(self.store.get(key, 0.0)) + float(amount)
        self.store[key] = total
        return total

    async def expire(self, key, seconds):
        self.expirations[key] = seconds
        return True

    async def expireat(self, key, ts):
        self.expirations[key] = ts
        return True

    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    """Just enough of a Redis pipeline for cost_guard's incrby/expireat/incrbyfloat calls."""

    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops: list[tuple[str, tuple]] = []

    def incrby(self, key, amount):
        self._ops.append(("incrby", (key, amount)))
        return self

    def expireat(self, key, ts):
        self._ops.append(("expireat", (key, ts)))
        return self

    def incrbyfloat(self, key, amount):
        self._ops.append(("incrbyfloat", (key, amount)))
        return self

    async def execute(self):
        for name, args in self._ops:
            await getattr(self._redis, name)(*args)
        self._ops.clear()


@pytest.fixture
def fake_redis():
    return FakeRedis()
