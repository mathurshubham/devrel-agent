"""End-to-end graph #2 tests against a real Postgres instance.

``PostClassification.source_meta`` and ``TopicCluster.posts`` are JSONB
columns, which SQLite cannot compile DDL for at all -- same constraint as
``tests/pipeline/test_graph_integration.py`` for graph #1. The whole module
is skipped (not failed) when Postgres isn't reachable.

Ingestion and the per-post LLM calls are mocked at the seam
``backend.pipeline.analyst_nodes`` imports them through
(``gather_analyst_posts``, ``structured_completion``, ``text_completion``) --
node function bodies resolve these as bare names from the module's globals
at call time, so patching the module attribute affects the already-built
graph's node callables too.
"""

import os
import time
from datetime import date, timedelta

import pytest
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import backend.pipeline.analyst_nodes as analyst_nodes_module
from backend.models import (
    AnalystRun,
    Base,
    IntelBrief,
    Organization,
    OrgLLMConfig,
    OrgSettings,
    PostClassification,
    PromptTemplate,
    PromptType,
    QuoteWorthyClaim,
    StanceObservation,
    TopicCluster,
)
from backend.pipeline.analyst_graph import run_analyst_pipeline, thread_id_for
from backend.pipeline.analyst_schemas import ClusterResult, QuotesResult, StanceResult, TriageResult
from backend.pipeline.graph import _psycopg_conn_string, setup_checkpointer_tables

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
        pytest.skip(f"Postgres not reachable at {TEST_DATABASE_URL}; skipping analyst graph integration tests")


@pytest.fixture
async def pg_session_factory(_skip_unless_postgres_up):
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


#: The seeded corpus's names (backend/seed.py::parse_analyst_prompts) --
#: content is a placeholder since structured_completion/text_completion are
#: mocked in every test here, but each node's early-degrade-to-defaults
#: branch triggers on an *empty* template, so these must exist and be
#: non-empty for the mocks to actually get exercised.
_ANALYST_PROMPT_NAMES = (
    "ANALYST-ANALYST_MASTER_CONTEXT",
    "ANALYST-ANALYST_TRIAGE_FILTER",
    "ANALYST-ANALYST_CLUSTERING",
    "ANALYST-ANALYST_STANCE",
    "ANALYST-ANALYST_QUOTES",
    "ANALYST-ANALYST_INTEL_BRIEF",
)


async def _seed_org(session_local) -> int:
    async with session_local() as db:
        org = Organization(clerk_org_id=f"org_{time.time_ns()}", name="Acme", is_active=True)
        db.add(org)
        await db.flush()
        db.add(OrgLLMConfig(org_id=org.id, model_name="test/mock-model"))
        for name in _ANALYST_PROMPT_NAMES:
            db.add(
                PromptTemplate(
                    org_id=None, platform=None, type=PromptType.ANALYST, name=name,
                    content=f"[test content for {name}] {{POST_TEXT}} {{PILLAR_TAG}} {{STANCE_LABEL}} {{WEEK_OF}}",
                )
            )
        await db.commit()
        return org.id


def _post(post_id: str, content: str = "We hit 95% on our eval benchmark") -> dict:
    return {
        "platform": "LINKEDIN",
        "post_id": post_id,
        "author": "jane",
        "author_name": "Jane Doe",
        "author_headline": "Head of AI",
        "author_profile_url": "https://linkedin.com/in/jane",
        "title": "",
        "content": content,
        "url": f"https://linkedin.com/posts/{post_id}",
        "top_comments": [],
        "reactions": 5,
        "comments": 1,
        "shares": 0,
        "engagement_score": 6,
        "posted_at": None,
    }


def _mock_gather(posts: list[dict], competitor_posts: list[dict] | None = None):
    async def _fake(db, org_id, org_settings, tokens, *, redis_client=None):
        return posts, (competitor_posts or []), []

    return _fake


def _mock_structured(*, decision="PROCESS_FULL", pillar="METRICS_ILLUSION", stance="PROBLEM_PRESENT"):
    async def _fake(prompt, model, schema, call_kwargs, **kw):
        response = type("R", (), {})()
        if schema is TriageResult:
            return TriageResult(relevance_score=5, signal_score=5, decision=decision), response
        if schema is ClusterResult:
            return ClusterResult(primary_pillar=pillar, secondary_pillars=[]), response
        if schema is StanceResult:
            return StanceResult(stance=stance, confidence="HIGH", evidence_quote="quote"), response
        if schema is QuotesResult:
            return QuotesResult(quotes=[]), response
        raise AssertionError(f"unexpected schema {schema}")

    return _fake


async def _mock_text_completion(prompt, model, call_kwargs, **kw):
    return f"# Mock Brief\n\n{len(prompt)} chars of context.", type("R", (), {})()


async def test_full_run_persists_classifications_clusters_stance_and_brief(monkeypatch, pg_session_factory):
    from datetime import date

    org_id = await _seed_org(pg_session_factory)
    posts = [_post("p1"), _post("p2")]
    week_of = date(2026, 8, 17)

    monkeypatch.setattr(analyst_nodes_module, "gather_analyst_posts", _mock_gather(posts))
    monkeypatch.setattr(analyst_nodes_module, "structured_completion", _mock_structured())
    monkeypatch.setattr(analyst_nodes_module, "text_completion", _mock_text_completion)

    async with pg_session_factory() as db:
        run = AnalystRun(org_id=org_id, week_of=week_of, status="RUNNING")
        db.add(run)
        await db.commit()
        run_id = run.id

    final_state = await run_analyst_pipeline(
        org_id, week_of, run_id, pg_session_factory, use_checkpointer=False
    )

    assert final_state["terminal_reason"] == "completed"
    assert final_state["brief_id"] is not None

    async with pg_session_factory() as db:
        classifications = (
            await db.execute(select(PostClassification).where(PostClassification.run_id == run_id))
        ).scalars().all()
        assert len(classifications) == 2
        assert {c.decision for c in classifications} == {"PROCESS_FULL"}
        assert classifications[0].source_meta["post_id"] in {"p1", "p2"}

        clusters = (await db.execute(select(TopicCluster).where(TopicCluster.run_id == run_id))).scalars().all()
        assert len(clusters) == 1
        assert clusters[0].pillar == "METRICS_ILLUSION"
        assert clusters[0].count == 2

        stances = (
            await db.execute(select(StanceObservation).where(StanceObservation.run_id == run_id))
        ).scalars().all()
        assert len(stances) == 2
        assert all(s.stance == "PROBLEM_PRESENT" for s in stances)

        brief = (await db.execute(select(IntelBrief).where(IntelBrief.org_id == org_id))).scalar_one()
        assert "Mock Brief" in brief.content_md

        completed_run = await db.get(AnalystRun, run_id)
        assert completed_run.status == "COMPLETED"
        assert completed_run.finished_at is not None


async def test_quotes_only_persisted_for_process_full(monkeypatch, pg_session_factory):
    org_id = await _seed_org(pg_session_factory)
    posts = [_post("p1")]

    async def _mixed_structured(prompt, model, schema, call_kwargs, **kw):
        response = type("R", (), {})()
        if schema is TriageResult:
            return TriageResult(decision="PROCESS_FULL"), response
        if schema is ClusterResult:
            return ClusterResult(primary_pillar="METRICS_ILLUSION"), response
        if schema is StanceResult:
            return StanceResult(stance="NEUTRAL"), response
        if schema is QuotesResult:
            from backend.pipeline.analyst_schemas import QuoteItem

            return QuotesResult(quotes=[QuoteItem(text="a standout quote here", angle="ANGLE-1")]), response
        raise AssertionError

    monkeypatch.setattr(analyst_nodes_module, "gather_analyst_posts", _mock_gather(posts))
    monkeypatch.setattr(analyst_nodes_module, "structured_completion", _mixed_structured)
    monkeypatch.setattr(analyst_nodes_module, "text_completion", _mock_text_completion)

    from datetime import date

    week_of = date(2026, 8, 17)
    async with pg_session_factory() as db:
        run = AnalystRun(org_id=org_id, week_of=week_of, status="RUNNING")
        db.add(run)
        await db.commit()
        run_id = run.id

    await run_analyst_pipeline(org_id, week_of, run_id, pg_session_factory, use_checkpointer=False)

    async with pg_session_factory() as db:
        quotes = (
            await db.execute(select(QuoteWorthyClaim).where(QuoteWorthyClaim.run_id == run_id))
        ).scalars().all()
        assert len(quotes) == 1
        assert quotes[0].quote == "a standout quote here"


async def test_cross_week_dedup_skips_previously_classified_posts(monkeypatch, pg_session_factory):
    from datetime import date

    org_id = await _seed_org(pg_session_factory)
    monkeypatch.setattr(analyst_nodes_module, "structured_completion", _mock_structured())
    monkeypatch.setattr(analyst_nodes_module, "text_completion", _mock_text_completion)

    # Week 1: classify p1 and p2.
    monkeypatch.setattr(analyst_nodes_module, "gather_analyst_posts", _mock_gather([_post("p1"), _post("p2")]))
    async with pg_session_factory() as db:
        run1 = AnalystRun(org_id=org_id, week_of=date(2026, 8, 17), status="RUNNING")
        db.add(run1)
        await db.commit()
        run1_id = run1.id
    await run_analyst_pipeline(org_id, date(2026, 8, 17), run1_id, pg_session_factory, use_checkpointer=False)

    # Week 2: p1 resurfaces (should be deduped), p3 is new.
    monkeypatch.setattr(analyst_nodes_module, "gather_analyst_posts", _mock_gather([_post("p1"), _post("p3")]))
    async with pg_session_factory() as db:
        run2 = AnalystRun(org_id=org_id, week_of=date(2026, 8, 24), status="RUNNING")
        db.add(run2)
        await db.commit()
        run2_id = run2.id
    final_state = await run_analyst_pipeline(org_id, date(2026, 8, 24), run2_id, pg_session_factory, use_checkpointer=False)

    assert [p["post_id"] for p in final_state["posts"]] == ["p3"]

    async with pg_session_factory() as db:
        week2_classifications = (
            await db.execute(select(PostClassification).where(PostClassification.run_id == run2_id))
        ).scalars().all()
        assert len(week2_classifications) == 1
        assert week2_classifications[0].source_meta["post_id"] == "p3"


async def test_momentum_reflects_prior_week_topic_clusters(monkeypatch, pg_session_factory):
    from datetime import date

    org_id = await _seed_org(pg_session_factory)
    monkeypatch.setattr(analyst_nodes_module, "structured_completion", _mock_structured())
    monkeypatch.setattr(analyst_nodes_module, "text_completion", _mock_text_completion)

    # Week 1: 2 posts on METRICS_ILLUSION.
    monkeypatch.setattr(analyst_nodes_module, "gather_analyst_posts", _mock_gather([_post("p1"), _post("p2")]))
    async with pg_session_factory() as db:
        run1 = AnalystRun(org_id=org_id, week_of=date(2026, 8, 17), status="RUNNING")
        db.add(run1)
        await db.commit()
        run1_id = run1.id
    await run_analyst_pipeline(org_id, date(2026, 8, 17), run1_id, pg_session_factory, use_checkpointer=False)

    # Week 2: 3 new posts, same pillar -- momentum should show curr=3 prev=2 delta=+1.
    monkeypatch.setattr(
        analyst_nodes_module, "gather_analyst_posts", _mock_gather([_post("p3"), _post("p4"), _post("p5")])
    )
    async with pg_session_factory() as db:
        run2 = AnalystRun(org_id=org_id, week_of=date(2026, 8, 24), status="RUNNING")
        db.add(run2)
        await db.commit()
        run2_id = run2.id
    final_state = await run_analyst_pipeline(org_id, date(2026, 8, 24), run2_id, pg_session_factory, use_checkpointer=False)

    assert final_state["prev_week_counts"] == {"METRICS_ILLUSION": 2}
    assert final_state["pillar_summaries"][0]["pillar"] == "METRICS_ILLUSION"
    assert final_state["pillar_summaries"][0]["count"] == 3


async def test_brief_upsert_idempotent_within_the_same_week(monkeypatch, pg_session_factory):
    from datetime import date

    org_id = await _seed_org(pg_session_factory)
    monkeypatch.setattr(analyst_nodes_module, "gather_analyst_posts", _mock_gather([_post("p1")]))
    monkeypatch.setattr(analyst_nodes_module, "structured_completion", _mock_structured())
    monkeypatch.setattr(analyst_nodes_module, "text_completion", _mock_text_completion)

    async def _run(week_of, run_id):
        async with pg_session_factory() as db:
            db.add(AnalystRun(id=run_id, org_id=org_id, week_of=week_of, status="RUNNING"))
            await db.commit()
        return await run_analyst_pipeline(org_id, week_of, run_id, pg_session_factory, use_checkpointer=False)

    from datetime import date

    week = date(2026, 8, 17)
    first = await _run(week, 101)
    second = await _run(week, 102)

    assert first["brief_id"] == second["brief_id"]

    async with pg_session_factory() as db:
        briefs = (await db.execute(select(IntelBrief).where(IntelBrief.org_id == org_id))).scalars().all()
        assert len(briefs) == 1


async def test_no_posts_completes_run_without_a_brief(monkeypatch, pg_session_factory):
    from datetime import date

    org_id = await _seed_org(pg_session_factory)
    monkeypatch.setattr(analyst_nodes_module, "gather_analyst_posts", _mock_gather([]))

    async with pg_session_factory() as db:
        run = AnalystRun(org_id=org_id, week_of=date(2026, 8, 17), status="RUNNING")
        db.add(run)
        await db.commit()
        run_id = run.id

    final_state = await run_analyst_pipeline(
        org_id, date(2026, 8, 17), run_id, pg_session_factory, use_checkpointer=False
    )
    assert final_state["terminal_reason"] == "no_posts"

    async with pg_session_factory() as db:
        run_row = await db.get(AnalystRun, run_id)
        assert run_row.status == "COMPLETED"
        briefs = (await db.execute(select(IntelBrief).where(IntelBrief.org_id == org_id))).scalars().all()
        assert briefs == []


# ---------------------------------------------------------------------------
# regression: same-week thread_id collision (M3 review finding #1)
# ---------------------------------------------------------------------------


async def _purge_checkpoint_thread(thread_id: str) -> None:
    """Deletes any existing checkpoint rows for ``thread_id``.

    ``checkpoints``/``checkpoint_blobs``/``checkpoint_writes`` live outside
    ``Base.metadata`` (``AsyncPostgresSaver`` manages them), so
    ``pg_session_factory``'s per-test ``drop_all``/``create_all`` never
    touches them -- they persist across test runs against a long-lived
    Postgres instance. ``org_id``/``run_id`` are autoincrement PKs that
    reset to the same low integers every test (fresh tables each time), so
    without this, a *previous* run of this exact test could leave a stale
    checkpoint under the very same thread_id this run is about to use --
    silently defeating the thing the test is trying to prove.
    """
    from psycopg import AsyncConnection

    conn_string = _psycopg_conn_string(TEST_DATABASE_URL)
    async with await AsyncConnection.connect(conn_string, autocommit=True) as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
            await cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,))
            await cur.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))


async def test_second_same_week_run_does_not_resume_the_first_runs_checkpoint(
    monkeypatch, pg_session_factory
):
    """Before ``thread_id`` was scoped by ``run_id``, a second AnalystRun for
    the same (org, week) resumed the *first* run's already-``END``
    checkpoint: it executed zero nodes and returned the first run's stale
    state, while its own AnalystRun row stayed RUNNING forever (which also
    permanently wedged the org-scoped 409 check on ``POST /run``). This
    exercises the real ``AsyncPostgresSaver`` checkpointer end to end (not
    ``use_checkpointer=False``, which every other test in this module uses)
    -- the collision only manifests through the checkpointer's resume path.
    """
    await setup_checkpointer_tables(database_url=TEST_DATABASE_URL)

    org_id = await _seed_org(pg_session_factory)
    week_of = date(2026, 8, 17)

    monkeypatch.setattr(analyst_nodes_module, "gather_analyst_posts", _mock_gather([_post("p1")]))
    monkeypatch.setattr(analyst_nodes_module, "structured_completion", _mock_structured())
    monkeypatch.setattr(analyst_nodes_module, "text_completion", _mock_text_completion)

    async with pg_session_factory() as db:
        run1 = AnalystRun(org_id=org_id, week_of=week_of, status="RUNNING")
        db.add(run1)
        await db.commit()
        run1_id = run1.id

    # See _purge_checkpoint_thread's docstring: org_id/run_id reset to the
    # same low integers every test run against a long-lived Postgres
    # instance, so a stale checkpoint from a *previous* run of this test
    # could otherwise already sit at this exact thread_id.
    await _purge_checkpoint_thread(thread_id_for(org_id, week_of.isoformat(), run1_id))

    first_state = await run_analyst_pipeline(
        org_id, week_of, run1_id, pg_session_factory,
        use_checkpointer=True, database_url=TEST_DATABASE_URL,
    )
    assert first_state["terminal_reason"] == "completed"

    # Second run, same org+week, a *different* run_id -- exactly the
    # scenario the reviewer reproduced failing.
    monkeypatch.setattr(analyst_nodes_module, "gather_analyst_posts", _mock_gather([_post("p2")]))
    async with pg_session_factory() as db:
        run2 = AnalystRun(org_id=org_id, week_of=week_of, status="RUNNING")
        db.add(run2)
        await db.commit()
        run2_id = run2.id

    await _purge_checkpoint_thread(thread_id_for(org_id, week_of.isoformat(), run2_id))

    second_state = await run_analyst_pipeline(
        org_id, week_of, run2_id, pg_session_factory,
        use_checkpointer=True, database_url=TEST_DATABASE_URL,
    )

    # The bug: without a run_id-scoped thread, this comes back with run1's
    # already-completed state (post "p1", zero nodes executed) instead of
    # actually re-running ingest..render_brief for run2's own post "p2".
    assert second_state["terminal_reason"] == "completed"
    assert [c["post_id"] for c in second_state["classifications"]] == ["p2"]
    assert second_state["brief_id"] is not None

    async with pg_session_factory() as db:
        run2_row = await db.get(AnalystRun, run2_id)
        assert run2_row.status == "COMPLETED"
        assert run2_row.finished_at is not None

        # Both runs' classifications persisted independently -- run2 was
        # never short-circuited into a no-op.
        run1_classifications = (
            await db.execute(select(PostClassification).where(PostClassification.run_id == run1_id))
        ).scalars().all()
        run2_classifications = (
            await db.execute(select(PostClassification).where(PostClassification.run_id == run2_id))
        ).scalars().all()
        assert [c.source_meta["post_id"] for c in run1_classifications] == ["p1"]
        assert [c.source_meta["post_id"] for c in run2_classifications] == ["p2"]


# ---------------------------------------------------------------------------
# regression: cross-week dedup lookback window (M3 review finding #10)
# ---------------------------------------------------------------------------


async def test_cross_week_dedup_only_looks_back_eight_weeks(monkeypatch, pg_session_factory):
    """A post classified more than ``_DEDUP_LOOKBACK_WEEKS`` weeks ago must
    resurface as "fresh" again -- the dedup scan is bounded to a rolling
    window, not the org's entire classification history."""
    org_id = await _seed_org(pg_session_factory)
    monkeypatch.setattr(analyst_nodes_module, "structured_completion", _mock_structured())
    monkeypatch.setattr(analyst_nodes_module, "text_completion", _mock_text_completion)

    this_week = date(2026, 8, 17)
    within_window_week = this_week - timedelta(weeks=3)
    outside_window_week = this_week - timedelta(weeks=9)

    async def _seed_classified_week(week_of, post_id):
        monkeypatch.setattr(analyst_nodes_module, "gather_analyst_posts", _mock_gather([_post(post_id)]))
        async with pg_session_factory() as db:
            run = AnalystRun(org_id=org_id, week_of=week_of, status="RUNNING")
            db.add(run)
            await db.commit()
            run_id = run.id
        await run_analyst_pipeline(org_id, week_of, run_id, pg_session_factory, use_checkpointer=False)

    await _seed_classified_week(outside_window_week, "p-old")
    await _seed_classified_week(within_window_week, "p-recent")

    # This week: both post ids resurface. "p-recent" (3 weeks ago, inside
    # the 8-week window) must dedupe out; "p-old" (9 weeks ago, outside the
    # window) must NOT -- it's treated as fresh again.
    monkeypatch.setattr(
        analyst_nodes_module, "gather_analyst_posts", _mock_gather([_post("p-old"), _post("p-recent")])
    )
    async with pg_session_factory() as db:
        run = AnalystRun(org_id=org_id, week_of=this_week, status="RUNNING")
        db.add(run)
        await db.commit()
        run_id = run.id

    final_state = await run_analyst_pipeline(
        org_id, this_week, run_id, pg_session_factory, use_checkpointer=False
    )

    assert [p["post_id"] for p in final_state["posts"]] == ["p-old"]
