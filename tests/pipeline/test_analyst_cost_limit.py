"""Analyst LLM cap enforcement (M3 review finding): analyst nodes must use
the *enforcing* ``check_and_record_llm_usage`` (same guard graph #1's
``persist_gate_node`` uses), not the metering-only ``record_llm_usage`` --
and a breached cap must terminate the run cleanly: the ``AnalystRun`` row
is marked FAILED (reason=cost_limit) and no half-written brief is left
behind.
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.models import AnalystRun, Base, IntelBrief, SystemLog, TargetAuthor
from backend.pipeline import analyst_nodes
from backend.pipeline.analyst_nodes import render_brief_node, triage_node
from tests.pipeline.conftest import FakeRedis


@pytest.fixture
async def sqlite_session_local():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                AnalystRun.__table__,
                IntelBrief.__table__,
                SystemLog.__table__,
                TargetAuthor.__table__,
            ],
        )

    session_local = async_sessionmaker(engine, expire_on_commit=False)
    yield session_local
    await engine.dispose()


class _CappedOutLLMConfig:
    """An OrgLLMConfig whose daily token cap (1 token) any real dispatch
    breaches immediately -- deterministic without needing to actually
    accumulate usage first."""

    model_name = "openrouter/test-model"
    encrypted_api_key = None
    encrypted_with_key_version = 1
    custom_base_url = None
    max_daily_llm_tokens = 1
    max_monthly_llm_cost_usd = None


async def _seed_run(session_local, *, org_id: int, run_id: int, week_of: date) -> None:
    async with session_local() as db:
        db.add(
            AnalystRun(
                id=run_id, org_id=org_id, week_of=week_of, status="RUNNING",
                started_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


def _config(session_local, *, templates: dict, run_id: int) -> dict:
    return {
        "configurable": {
            "session_local": session_local,
            "redis_client": FakeRedis(),
            "llm_config": _CappedOutLLMConfig(),
            "templates": templates,
            "run_id": run_id,
        }
    }


async def test_render_brief_node_terminates_cleanly_on_cost_limit_breach(monkeypatch, sqlite_session_local):
    async def _unexpected_text_completion(*a, **kw):
        raise AssertionError("text_completion must not be called once the cap is breached")

    monkeypatch.setattr(analyst_nodes, "text_completion", _unexpected_text_completion)

    await _seed_run(sqlite_session_local, org_id=1, run_id=1, week_of=date(2026, 8, 17))

    state = {
        "org_id": 1, "run_id": 1, "week_of": "2026-08-17",
        "classifications": [], "competitor_posts": [], "prev_week_counts": {}, "triage_counts": {},
    }
    config = _config(sqlite_session_local, templates={"brief": "BRIEF Week of {WEEK_OF}"}, run_id=1)

    result = await render_brief_node(state, config)

    assert result == {"terminal": True, "terminal_reason": "cost_limit"}

    async with sqlite_session_local() as db:
        run = await db.get(AnalystRun, 1)
        assert run.status == "FAILED"
        assert run.finished_at is not None

        briefs = (await db.execute(select(IntelBrief).where(IntelBrief.org_id == 1))).scalars().all()
        assert briefs == []  # no half-written brief

        logs = (await db.execute(select(SystemLog).where(SystemLog.org_id == 1))).scalars().all()
        assert any("cost_limit" in log.message for log in logs)


async def test_triage_node_terminates_the_run_on_cost_limit_breach(monkeypatch, sqlite_session_local):
    async def _unexpected_structured_completion(*a, **kw):
        raise AssertionError("structured_completion must not be called once the cap is breached")

    monkeypatch.setattr(analyst_nodes, "structured_completion", _unexpected_structured_completion)

    await _seed_run(sqlite_session_local, org_id=1, run_id=1, week_of=date(2026, 8, 17))

    posts = [{"post_id": "p1", "content": "hello there", "platform": "LINKEDIN"}]
    state = {"org_id": 1, "run_id": 1, "week_of": "2026-08-17", "posts": posts}
    config = _config(sqlite_session_local, templates={"triage": "TRIAGE {POST_TEXT}"}, run_id=1)

    result = await triage_node(state, config)

    assert result["terminal"] is True
    assert result["terminal_reason"] == "cost_limit"

    async with sqlite_session_local() as db:
        run = await db.get(AnalystRun, 1)
        assert run.status == "FAILED"


async def test_cost_cap_check_is_a_noop_without_a_redis_client():
    """redis_client is None (no cap store reachable) -- degrade to
    "proceed unmetered" rather than crash, same as the old metering-only
    record_llm_usage's None-guard behaviour."""
    breach = await analyst_nodes._check_cost_cap(1, 1_000_000, "any/model", _CappedOutLLMConfig(), None)
    assert breach is None
