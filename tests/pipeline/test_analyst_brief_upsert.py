"""render_brief_node's IntelBrief upsert -- against a real (in-memory)
SQLite session, not a fake.

IntelBrief/AnalystRun/SystemLog carry no JSONB columns or Postgres-only
index options, so (like tests/test_auth_jit.py's sqlite_session fixture)
they're fully portable -- unlike PostClassification/TopicCluster, which
need real Postgres (tests/test_analyst_postgres_integration.py).
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.models import AnalystRun, Base, IntelBrief, SystemLog
from backend.pipeline import analyst_nodes
from backend.pipeline.analyst_nodes import render_brief_node


@pytest.fixture
async def sqlite_session_local():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[AnalystRun.__table__, IntelBrief.__table__, SystemLog.__table__],
        )

    session_local = async_sessionmaker(engine, expire_on_commit=False)
    yield session_local
    await engine.dispose()


class _FakeLLMConfig:
    model_name = "openrouter/test-model"
    encrypted_api_key = None
    encrypted_with_key_version = 1
    custom_base_url = None


@pytest.fixture(autouse=True)
def _patch_lookups(monkeypatch):
    async def _fake_llm_config(db, org_id):
        return _FakeLLMConfig()

    async def _fake_templates(db, org_id):
        return {"brief": "BRIEF Week of {WEEK_OF}"}

    monkeypatch.setattr(analyst_nodes, "get_org_llm_config", _fake_llm_config)
    monkeypatch.setattr(analyst_nodes, "get_analyst_templates", _fake_templates)


async def _seed_run(session_local, org_id: int, run_id: int, week_of: date) -> None:
    async with session_local() as db:
        db.add(AnalystRun(id=run_id, org_id=org_id, week_of=week_of, status="RUNNING", started_at=datetime.now(timezone.utc)))
        await db.commit()


def _config(session_local):
    return {"configurable": {"session_local": session_local, "redis_client": None}}


async def test_render_brief_creates_a_new_brief_and_completes_the_run(monkeypatch, sqlite_session_local):
    async def _fake_text_completion(prompt, model, call_kwargs, **kw):
        assert "Week of 2026-08-17" in prompt
        return "# Weekly Brief\n\nAll good.", type("R", (), {})()

    monkeypatch.setattr(analyst_nodes, "text_completion", _fake_text_completion)

    await _seed_run(sqlite_session_local, org_id=1, run_id=1, week_of=date(2026, 8, 17))

    state = {
        "org_id": 1, "run_id": 1, "week_of": "2026-08-17",
        "classifications": [], "competitor_posts": [], "prev_week_counts": {}, "triage_counts": {},
    }
    result = await render_brief_node(state, _config(sqlite_session_local))

    assert result["terminal"] is True
    brief_id = result["brief_id"]

    async with sqlite_session_local() as db:
        brief = await db.get(IntelBrief, brief_id)
        assert brief.content_md == "# Weekly Brief\n\nAll good."
        run = await db.get(AnalystRun, 1)
        assert run.status == "COMPLETED"
        assert run.finished_at is not None


async def test_render_brief_upsert_is_idempotent_for_the_same_org_and_week(monkeypatch, sqlite_session_local):
    calls = {"n": 0}

    async def _fake_text_completion(prompt, model, call_kwargs, **kw):
        calls["n"] += 1
        return f"# Brief version {calls['n']}", type("R", (), {})()

    monkeypatch.setattr(analyst_nodes, "text_completion", _fake_text_completion)

    await _seed_run(sqlite_session_local, org_id=1, run_id=1, week_of=date(2026, 8, 17))
    await _seed_run(sqlite_session_local, org_id=1, run_id=2, week_of=date(2026, 8, 17))

    base_state = {
        "org_id": 1, "week_of": "2026-08-17",
        "classifications": [], "competitor_posts": [], "prev_week_counts": {}, "triage_counts": {},
    }

    first = await render_brief_node({**base_state, "run_id": 1}, _config(sqlite_session_local))
    second = await render_brief_node({**base_state, "run_id": 2}, _config(sqlite_session_local))

    # Same brief row (unique org_id+week_of) updated in place, not duplicated.
    assert first["brief_id"] == second["brief_id"]

    async with sqlite_session_local() as db:
        from sqlalchemy import select

        rows = (await db.execute(select(IntelBrief).where(IntelBrief.org_id == 1))).scalars().all()
        assert len(rows) == 1
        assert rows[0].content_md == "# Brief version 2"


async def test_render_brief_llm_failure_fails_the_run_and_writes_no_brief(monkeypatch, sqlite_session_local):
    async def _fake_text_completion(*a, **kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(analyst_nodes, "text_completion", _fake_text_completion)

    await _seed_run(sqlite_session_local, org_id=1, run_id=1, week_of=date(2026, 8, 17))

    state = {
        "org_id": 1, "run_id": 1, "week_of": "2026-08-17",
        "classifications": [], "competitor_posts": [], "prev_week_counts": {}, "triage_counts": {},
    }
    result = await render_brief_node(state, _config(sqlite_session_local))

    # The run must FAIL loudly, mirror the cost-limit path, and write NO
    # IntelBrief -- persisting an error string as a brief poisons next
    # week's momentum inputs and shows a green COMPLETED chip over a failure.
    assert result["terminal_reason"] == "llm_error"
    assert "brief_id" not in result
    from sqlalchemy import select
    async with sqlite_session_local() as db:
        briefs = (await db.execute(select(IntelBrief))).scalars().all()
        assert briefs == []
        run = await db.get(AnalystRun, 1)
        assert run.status == "FAILED"
        assert run.finished_at is not None


async def test_render_brief_is_a_noop_when_state_is_terminal(sqlite_session_local):
    result = await render_brief_node({"terminal": True}, _config(sqlite_session_local))
    assert result == {}
