"""GET/PATCH /api/org/settings against a real Postgres session.

``OrgSettings.pillar_taxonomy``/``actor_overrides`` are JSONB columns, so
(unlike the router tests in tests/api/, which fake the DB entirely) a
create-then-fetch round trip through the real column defaults needs a real
Postgres session -- same skip-without-docker convention as
tests/test_postgres_integration.py.
"""
import os
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.database import get_db
from backend.limiter import limiter
from backend.main import app
from backend.models import Base, Organization, User, UserRole
from backend.utils.auth import get_current_session

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:test@localhost:55432/test"
)


async def _postgres_reachable() -> bool:
    try:
        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture
async def _skip_unless_postgres_up():
    if not await _postgres_reachable():
        pytest.skip(f"Postgres not reachable at {TEST_DATABASE_URL}; skipping org-settings integration tests")


@pytest.fixture
async def pg_client(_skip_unless_postgres_up):
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_local = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with session_local() as seed_db:
        org = Organization(clerk_org_id=f"org_{time.time_ns()}", name="Acme", is_active=True)
        user = User(clerk_user_id=f"user_{time.time_ns()}", email="admin@acme.test", role=UserRole.ADMIN)
        seed_db.add_all([org, user])
        await seed_db.commit()
        org_id, user_id = org.id, user.id

    async def _fake_session():
        return {
            "org_id": org_id, "user_id": user_id, "clerk_org_id": "org_test",
            "clerk_user_id": "user_test", "role": "ADMIN",
        }

    async def _fake_db():
        async with session_local() as db:
            yield db

    app.dependency_overrides[get_current_session] = _fake_session
    app.dependency_overrides[get_db] = _fake_db
    previously_enabled = limiter.enabled
    limiter.enabled = False

    try:
        yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    finally:
        limiter.enabled = previously_enabled
        app.dependency_overrides.clear()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_get_settings_defaults_before_any_write(pg_client):
    async with pg_client as ac:
        resp = await ac.get("/api/org/settings")
    assert resp.status_code == 200
    assert resp.json()["analyst_enabled"] is False
    assert resp.json()["apify_monthly_budget_usd"] == 50.0


async def test_patch_creates_row_and_applies_real_column_defaults(pg_client):
    """A partial PATCH creating the org's first-ever settings row still
    round-trips correctly once actually flushed to Postgres -- unlike the
    in-memory FakeDB used by tests/api/test_org_settings.py, a real INSERT
    applies every column's SQLAlchemy-side default for fields the payload
    didn't touch."""
    async with pg_client as ac:
        patch_resp = await ac.patch("/api/org/settings", json={"analyst_enabled": True})
        assert patch_resp.status_code == 200
        body = patch_resp.json()
        assert body["analyst_enabled"] is True
        assert body["disclosure_reddit"] is True  # column default, never submitted
        assert body["apify_monthly_budget_usd"] == 50.0  # column default

        get_resp = await ac.get("/api/org/settings")
    assert get_resp.json()["analyst_enabled"] is True


async def test_patch_round_trips_jsonb_pillar_taxonomy(pg_client):
    taxonomy = [{"tag": "CUSTOM_PILLAR", "tier": "PRIMARY"}, {"tag": "SECOND", "tier": "SECONDARY"}]

    async with pg_client as ac:
        patch_resp = await ac.patch("/api/org/settings", json={"pillar_taxonomy": taxonomy})
        assert patch_resp.status_code == 200
        assert patch_resp.json()["pillar_taxonomy"] == taxonomy

        get_resp = await ac.get("/api/org/settings")
    assert get_resp.json()["pillar_taxonomy"] == taxonomy


async def test_patch_partial_update_preserves_earlier_writes(pg_client):
    async with pg_client as ac:
        await ac.patch("/api/org/settings", json={"reply_hook": "Banner", "apify_monthly_budget_usd": 75.0})
        second = await ac.patch("/api/org/settings", json={"analyst_enabled": True})

    body = second.json()
    assert body["analyst_enabled"] is True
    assert body["reply_hook"] == "Banner"  # earlier write survives the second PATCH
    assert body["apify_monthly_budget_usd"] == 75.0
