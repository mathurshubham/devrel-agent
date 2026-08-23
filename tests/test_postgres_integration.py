"""
Integration tests against a real Postgres (+ Redis) instance for the bits
that plain aiosqlite can't exercise faithfully:

  - PostedHistory's INSERT ... ON CONFLICT DO NOTHING idempotency (finding #1)
    -- needs a real Postgres unique constraint + ON CONFLICT support.
  - draft_replies.campaign_id ON DELETE CASCADE (finding #4) -- needs a real
    FK with ondelete behavior; sqlite's FK enforcement is opt-in/partial.
  - Two consecutive Celery-style asyncio.run() invocations of scheduler_tick
    not raising "RuntimeError: Event loop is closed" (finding #5) -- needs a
    real asyncpg engine (asyncpg pools are what actually break across
    asyncio.run() calls; sqlite+aiosqlite doesn't reproduce the bug).

Point these at a throwaway Postgres/Redis via:
    docker run --rm -d -p 55432:5432 -e POSTGRES_PASSWORD=test -e POSTGRES_DB=test postgres:15-alpine
    docker run --rm -d -p 56379:6379 redis:7-alpine

and optionally override TEST_DATABASE_URL / TEST_REDIS_URL. The whole module
is skipped (not failed) if neither is reachable, so `pytest tests/` stays
green in environments without Docker.
"""
import asyncio
import os
import time

import pytest
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.models import Base, Campaign, CampaignStatus, DraftReply, DraftStatus, \
    Organization, PlatformEnum, PostedHistory, ReplyType

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:test@localhost:55432/test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:56379/0")


async def _postgres_reachable() -> bool:
    try:
        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


async def _redis_reachable() -> bool:
    try:
        client = redis.from_url(TEST_REDIS_URL)
        await client.ping()
        await client.aclose()
        return True
    except Exception:
        return False


@pytest.fixture
async def _skip_unless_infra_up():
    if not await _postgres_reachable():
        pytest.skip(f"Postgres not reachable at {TEST_DATABASE_URL}; skipping integration tests")
    if not await _redis_reachable():
        pytest.skip(f"Redis not reachable at {TEST_REDIS_URL}; skipping integration tests")


@pytest.fixture
async def pg_session_factory(_skip_unless_infra_up):
    """Fresh engine/schema per test, torn down afterward."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)

    session_local = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield session_local
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def _make_org_and_campaign(session_local):
    async with session_local() as db:
        org = Organization(clerk_org_id=f"org_{time.time_ns()}", name="Test Org", is_active=True)
        db.add(org)
        await db.flush()

        campaign = Campaign(
            org_id=org.id,
            platform=PlatformEnum.REDDIT,
            name="Test Campaign",
            status=CampaignStatus.ACTIVE,
            poll_frequency_minutes=240,
        )
        db.add(campaign)
        await db.commit()
        return org.id, campaign.id


# ── Finding #1: idempotent PostedHistory insert ──────────────────────────────

async def test_posted_history_insert_is_idempotent(pg_session_factory):
    org_id, campaign_id = await _make_org_and_campaign(pg_session_factory)

    async def _insert_once(db):
        await db.execute(
            pg_insert(PostedHistory)
            .values(org_id=org_id, platform=PlatformEnum.REDDIT, post_id="abc123")
            .on_conflict_do_nothing(constraint="uq_posted_history_org_platform_post")
        )
        await db.commit()

    async with pg_session_factory() as db:
        await _insert_once(db)
    async with pg_session_factory() as db:
        # Second insert for the exact same (org, platform, post_id) must not
        # raise IntegrityError.
        await _insert_once(db)

    async with pg_session_factory() as db:
        result = await db.execute(
            text(
                "SELECT count(*) FROM posted_history "
                "WHERE org_id = :org_id AND post_id = 'abc123'"
            ),
            {"org_id": org_id},
        )
        assert result.scalar_one() == 1


# ── Finding #4: cascade delete draft_replies when their campaign is deleted ──

async def test_campaign_delete_cascades_to_draft_replies(pg_session_factory):
    org_id, campaign_id = await _make_org_and_campaign(pg_session_factory)

    async with pg_session_factory() as db:
        draft = DraftReply(
            org_id=org_id,
            campaign_id=campaign_id,
            platform=PlatformEnum.REDDIT,
            post_id="post-1",
            reply_type=ReplyType.NEW_COMMENT,
            status=DraftStatus.PENDING,
        )
        db.add(draft)
        await db.commit()

    async with pg_session_factory() as db:
        campaign = await db.get(Campaign, campaign_id)
        await db.delete(campaign)
        await db.commit()  # must not 500/raise despite the drafts row above

    async with pg_session_factory() as db:
        result = await db.execute(
            text("SELECT count(*) FROM draft_replies WHERE campaign_id = :cid"),
            {"cid": campaign_id},
        )
        assert result.scalar_one() == 0


# ── Finding #5: fresh engine/redis client per Celery task invocation ────────

def test_two_consecutive_scheduler_ticks_do_not_reuse_a_closed_loop(monkeypatch):
    """
    Simulates what Celery actually does: two independent asyncio.run() calls
    into scheduler_tick, back to back in the same process. Before the fix,
    the second call raised "RuntimeError: Event loop is closed" because the
    module-level redis client / SQLAlchemy engine were bound to the first
    call's (now-closed) loop.

    This test is deliberately synchronous (not `async def`): scheduler_tick
    itself does asyncio.run() internally, and asyncio.run() cannot be called
    from inside an already-running event loop -- which is exactly what an
    `async def` pytest-asyncio test would be. Each async phase below gets
    its own top-level asyncio.run(), same as scheduler_tick's.
    """
    if not asyncio.run(_postgres_reachable()) or not asyncio.run(_redis_reachable()):
        pytest.skip(f"Postgres/Redis not reachable at {TEST_DATABASE_URL} / {TEST_REDIS_URL}")

    import backend.database as database_module
    monkeypatch.setattr(database_module, "DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)

    # Avoid actually dispatching to a Celery broker/worker for this test.
    from backend.tasks import scheduler as scheduler_module
    monkeypatch.setattr(scheduler_module.celery_app, "send_task", lambda *a, **k: None)

    async def _setup():
        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await conn.run_sync(Base.metadata.create_all)
        session_local = async_sessionmaker(bind=engine, expire_on_commit=False)
        org_id, campaign_id = await _make_org_and_campaign(session_local)
        await engine.dispose()
        return org_id, campaign_id

    async def _enqueue_due(campaign_id):
        redis_client = redis.from_url(TEST_REDIS_URL)
        try:
            await redis_client.zadd(scheduler_module.SCHEDULER_KEY, {str(campaign_id): time.time() - 10})
        finally:
            await redis_client.aclose()

    async def _teardown():
        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    org_id, campaign_id = asyncio.run(_setup())
    try:
        asyncio.run(_enqueue_due(campaign_id))

        # First asyncio.run() invocation -- exactly what Celery does per task.
        scheduler_module.scheduler_tick.run()

        # Re-enqueue so the second tick has something due again, then run a
        # second, fully independent asyncio.run() invocation. This is
        # exactly the scenario that used to raise "Event loop is closed".
        asyncio.run(_enqueue_due(campaign_id))
        scheduler_module.scheduler_tick.run()  # must not raise RuntimeError
    finally:
        asyncio.run(_teardown())
