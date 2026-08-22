"""Router-level tests for /api/org/apify.

These exercise the FastAPI wiring (dependency signatures, session shape)
that pure service-level unit tests cannot catch — a previous bug had the
router reading `session.org_id` off the dict-shaped auth session, which
500'd on every request while all unit tests stayed green.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.database import get_db
from backend.main import app
from backend.utils.auth import get_current_session

FAKE_SESSION = {
    "org_id": 1,
    "user_id": 1,
    "clerk_org_id": "org_test",
    "clerk_user_id": "user_test",
    "role": "ADMIN",
}


@pytest.fixture
def client():
    async def fake_session():
        return FAKE_SESSION

    async def fake_db():
        db = MagicMock()
        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        empty.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=empty)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        yield db

    app.dependency_overrides[get_current_session] = fake_session
    app.dependency_overrides[get_db] = fake_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def test_list_tokens_uses_dict_session(client):
    async with client as ac:
        resp = await ac.get("/api/org/apify/tokens")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_delete_missing_token_404s_not_500s(client):
    async with client as ac:
        resp = await ac.delete("/api/org/apify/tokens/999")
    assert resp.status_code == 404
