"""Regression pin for the strategist-batch concurrency bug (PRD V7 §5.3/§9).

Ported from social-agent/backend/tests/test_pipeline_concurrency.py. Original
failure (seen in Neon logs):

    Method 'close()' can't be called here; method '_prepare_impl()' is
    already in progress and this would cause an unexpected state change
    to <SessionTransactionState.CLOSED: 5>

Cause: the strategist stage runs batches concurrently via
``asyncio.gather`` (semaphore-limited to ``BATCH_CONCURRENCY``), but
``AsyncSession`` is not safe for concurrent use, so two coroutines
executing/committing on the same session at once corrupt its transaction
state.

The fix, mirrored in ``backend.pipeline.nodes.strategist_node``'s
``_draft_batch`` closure, opens a fresh ``async with session_local() as
batch_db:`` per concurrent batch. These tests lock in that invariant: a
shared session under concurrent batches must fail, and one-session-per-batch
must succeed and persist every row.
"""

import asyncio

import pytest
from sqlalchemy import Column, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from backend.pipeline.strategist import BATCH_CONCURRENCY

Base = declarative_base()


class _Draft(Base):
    __tablename__ = "concurrency_test_drafts"
    id = Column(Integer, primary_key=True)
    post_id = Column(String, nullable=False)


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _chunks():
    return [
        [f"b0-p{i}" for i in range(4)],
        [f"b1-p{i}" for i in range(4)],
        [f"b2-p{i}" for i in range(4)],
    ]


async def _persist(db: AsyncSession, post_ids):
    for pid in post_ids:
        db.add(_Draft(post_id=pid))
    # An interleaved execute() is what races with another coroutine's
    # commit()/close() on a shared session.
    await db.execute(select(_Draft))
    await db.commit()


async def test_shared_session_across_batches_raises(session_factory):
    """Reproduces the original bug: one session, concurrent batches -> error.

    The session is opened/closed manually (not via ``async with``): once the
    concurrent writes corrupt its transaction state, even closing it can
    raise a second time -- that follow-on failure is part of the same bug,
    not a separate problem this test needs to also assert on.
    """
    shared_db = session_factory()
    try:
        async def batch(post_ids):
            await asyncio.sleep(0)
            await _persist(shared_db, post_ids)

        with pytest.raises(Exception) as exc:
            await asyncio.gather(*[batch(c) for c in _chunks()])

        msg = str(exc.value).lower()
        assert "in progress" in msg or "concurrent" in msg or "illegalstate" in msg, (
            f"expected a concurrent-session-use error, got: {exc.value!r}"
        )
    finally:
        try:
            await shared_db.close()
        except Exception:
            pass


async def test_session_per_batch_succeeds(session_factory):
    """The fix: each batch gets its own session -> no race, all rows saved."""
    sem = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def guarded_batch(post_ids):
        async with sem:
            # This is exactly the fix in backend.pipeline.nodes.strategist_node.
            async with session_factory() as batch_db:
                await asyncio.sleep(0)
                await _persist(batch_db, post_ids)

    await asyncio.gather(*[guarded_batch(c) for c in _chunks()])

    async with session_factory() as db:
        rows = (await db.execute(select(_Draft.post_id))).scalars().all()

    expected = {pid for chunk in _chunks() for pid in chunk}
    assert set(rows) == expected
    assert len(rows) == 12
