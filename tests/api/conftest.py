"""Shared router-test scaffolding for the new Analyst/Analytics/Org-settings
endpoints -- follows tests/ingestion/test_router.py's dependency-override
pattern, generalized into a reusable fake AsyncSession.
"""
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.database import get_db
from backend.limiter import limiter
from backend.main import app
from backend.utils.auth import get_current_session

FAKE_SESSION = {
    "org_id": 1,
    "user_id": 1,
    "clerk_org_id": "org_test",
    "clerk_user_id": "user_test",
    "role": "ADMIN",
}


class FakeDB:
    """A scriptable AsyncSession stand-in.

    ``queue_execute_result`` pushes a canned result for the next
    ``db.execute(...)`` call (FIFO) -- when the queue is empty, ``execute``
    returns an "empty" result (``scalar_one_or_none() is None``,
    ``scalars().all() == []``), which is what most of these endpoints see
    for an org with no rows yet.

    ``add()`` assigns an autoincrementing ``id`` to any object that doesn't
    have one yet (mimicking a flush-assigned identity column) and remembers
    it so a later ``db.get(Model, id)`` can find it -- this is what lets
    create-then-refresh handlers round-trip without a real database.
    """

    def __init__(self):
        self._next_id = 1
        self._execute_results: list = []
        self.added: list = []
        self.deleted: list = []
        self.committed = 0

    def queue_execute_result(self, *, scalar_one_or_none=None, scalars_all=None):
        result = MagicMock()
        result.scalar_one_or_none.return_value = scalar_one_or_none
        result.scalars.return_value.all.return_value = scalars_all or []
        # ``.scalars().first()`` -- the MultipleResultsFound-safe pattern
        # (``select(...).order_by(...).limit(1)`` + ``scalars().first()``)
        # used in place of a bare ``scalar_one_or_none()`` wherever the
        # query has no unique constraint guaranteeing at most one row.
        # Defaults to whatever ``scalar_one_or_none`` was given so tests
        # written against either style see the same canned row.
        first_value = scalar_one_or_none
        if first_value is None and scalars_all:
            first_value = scalars_all[0]
        result.scalars.return_value.first.return_value = first_value
        result.all.return_value = scalars_all or []
        self._execute_results.append(result)

    async def execute(self, *args, **kwargs):
        if self._execute_results:
            return self._execute_results.pop(0)
        empty = MagicMock()
        empty.scalar_one_or_none.return_value = None
        empty.scalars.return_value.all.return_value = []
        empty.scalars.return_value.first.return_value = None
        empty.all.return_value = []
        return empty

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.committed += 1

    async def refresh(self, obj):
        pass

    async def delete(self, obj):
        self.deleted.append(obj)
        if obj in self.added:
            self.added.remove(obj)

    async def get(self, model, pk):
        for obj in self.added:
            if isinstance(obj, model) and obj.id == pk:
                return obj
        return None


@pytest.fixture
def fake_db():
    return FakeDB()


@pytest.fixture
def client(fake_db):
    async def _fake_session():
        return FAKE_SESSION

    async def _fake_db_dep():
        yield fake_db

    app.dependency_overrides[get_current_session] = _fake_session
    app.dependency_overrides[get_db] = _fake_db_dep

    # slowapi's Limiter is configured with a Redis storage_uri
    # (backend/limiter.py) -- router tests have no Redis to talk to, and
    # rate limiting itself isn't what these tests exercise, so disable it
    # for the duration of the test rather than requiring a live broker.
    previously_enabled = limiter.enabled
    limiter.enabled = False
    try:
        yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    finally:
        limiter.enabled = previously_enabled
        app.dependency_overrides.clear()
