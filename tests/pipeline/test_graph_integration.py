"""End-to-end graph #1 tests against a real Postgres instance.

``backend.models`` uses JSONB columns (``Campaign.keywords``,
``Campaign.platform_config``, ``DraftReply.top_comments``, ...) which SQLite
cannot compile DDL for at all (confirmed: SQLAlchemy raises
``UnsupportedCompilationError`` on ``visit_JSONB``) -- these tests need a
real Postgres, same as ``tests/test_postgres_integration.py``. The whole
module is skipped (not failed) when Postgres isn't reachable, exactly like
that file, so `pytest tests/` stays green without Docker.

Redis stays faked (``tests/pipeline/conftest.FakeRedis``) -- nothing here
needs a real Redis server, only Postgres's JSONB/constraint support.

Ingestion and the LLM calls are mocked at the seam ``backend.pipeline.nodes``
imports them through (``ingest_campaign``, ``run_scout``,
``run_strategist_batch``) -- node function bodies resolve these as bare
names from the module's globals at call time, so patching the module
attribute affects already-graph-registered node callables too.
"""

import os
import time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import backend.pipeline.nodes as nodes_module
from backend.ingestion.service import BudgetExceededError
from backend.models import (
    Base,
    Campaign,
    CampaignStatus,
    DraftReply,
    DraftStatus,
    EngagementOutcome,
    Organization,
    OrgLLMConfig,
    OrgSettings,
    PlatformEnum,
    PromptTemplate,
    PromptType,
    ReplyType,
    SubredditSafetyProfile,
)
from backend.pipeline.graph import run_pipeline, setup_checkpointer_tables
from backend.pipeline.scout import ScoutOutput, ScoutSelection
from backend.pipeline.templates import get_top_angles_hint

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:test@localhost:55432/test"
)

ANGLE_NAME = "REDDIT-ANGLE-1: Test Angle"


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
        pytest.skip(f"Postgres not reachable at {TEST_DATABASE_URL}; skipping graph integration tests")


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


def _post(post_id: str, content: str = "We hit 95% on our eval benchmark", **overrides) -> dict:
    base = {
        "platform": "REDDIT",
        "post_id": post_id,
        "author": "some_user",
        "author_name": "some_user",
        "author_headline": "",
        "author_profile_url": "https://reddit.com/user/some_user",
        "title": "A post about evals",
        "content": content,
        "url": f"https://reddit.com/r/LLMDevs/comments/{post_id}/",
        "top_comments": [],
        "reactions": 5,
        "comments": 1,
        "shares": 0,
        "engagement_score": 6,
        "posted_at": None,
    }
    base.update(overrides)
    return base


async def _seed_org_and_campaign(session_local, *, daily_draft_cap: int = 10) -> tuple[int, int]:
    async with session_local() as db:
        org = Organization(clerk_org_id=f"org_{time.time_ns()}", name="Acme", is_active=True)
        db.add(org)
        await db.flush()

        db.add(OrgLLMConfig(org_id=org.id, model_name="test/mock-model"))
        db.add(OrgSettings(org_id=org.id, disclosure_reddit=False))
        db.add(
            PromptTemplate(
                org_id=None,
                platform=PlatformEnum.REDDIT,
                type=PromptType.MASTER_CONTEXT,
                name="REDDIT-MASTER_CONTEXT",
                content="[test master context]",
            )
        )
        db.add(
            PromptTemplate(
                org_id=None,
                platform=PlatformEnum.REDDIT,
                type=PromptType.ANGLE,
                name=ANGLE_NAME,
                content="[MASTER CONTEXT BLOCK]\nReply about {POST_TEXT} in r/{SUBREDDIT}.",
            )
        )

        campaign = Campaign(
            org_id=org.id,
            platform=PlatformEnum.REDDIT,
            name="Test Campaign",
            value="LLMDevs",
            status=CampaignStatus.ACTIVE,
            poll_frequency_minutes=240,
            daily_draft_cap=daily_draft_cap,
        )
        db.add(campaign)
        await db.commit()
        return org.id, campaign.id


def _mock_ingest(posts: list[dict], *, error: Exception | None = None, call_counter: dict | None = None):
    async def _fake(db, campaign, org_settings, vault_tokens, redis_client=None):
        if call_counter is not None:
            call_counter["n"] += 1
        if error is not None:
            raise error
        return posts

    return _fake


def _mock_scout(selections: list[ScoutSelection]):
    async def _fake(posts, angle_names, *, platform, model, call_kwargs, instructions=None, hint="", acompletion_fn=None):
        return ScoutOutput(selections=list(selections))

    return _fake


def _mock_strategist_batch(prefix: str = "Draft for"):
    async def _fake(items, model, call_kwargs, *, acompletion_fn=None):
        return {item["post_id"]: f"{prefix} {item['post_id']}" for item in items}

    return _fake


# --- happy path ----------------------------------------------------------------


async def test_happy_path_persists_a_pending_draft(pg_session_factory, fake_redis, monkeypatch):
    org_id, campaign_id = await _seed_org_and_campaign(pg_session_factory)
    posts = [_post("p1")]

    monkeypatch.setattr(nodes_module, "ingest_campaign", _mock_ingest(posts))
    monkeypatch.setattr(
        nodes_module,
        "run_scout",
        _mock_scout([ScoutSelection(post_id="p1", angle_name=ANGLE_NAME, confidence=0.9, reasoning="on topic")]),
    )
    monkeypatch.setattr(nodes_module, "run_strategist_batch", _mock_strategist_batch())

    final_state = await run_pipeline(
        campaign_id, time.time(), pg_session_factory, fake_redis, use_checkpointer=False
    )

    assert final_state.get("terminal_reason") is None
    assert len(final_state["persisted_draft_ids"]) == 1

    async with pg_session_factory() as db:
        draft = await db.get(DraftReply, final_state["persisted_draft_ids"][0])
        assert draft.status == DraftStatus.PENDING
        assert draft.campaign_id == campaign_id
        assert draft.org_id == org_id
        assert draft.post_id == "p1"
        assert draft.angle_name == ANGLE_NAME
        assert "p1" in draft.ai_draft_text
        assert draft.reply_type == ReplyType.NEW_COMMENT
        assert draft.reply_target_url == posts[0]["url"]


# --- budget exceeded -------------------------------------------------------------


async def test_budget_exceeded_ends_the_run_with_no_drafts(pg_session_factory, fake_redis, monkeypatch):
    org_id, campaign_id = await _seed_org_and_campaign(pg_session_factory)

    monkeypatch.setattr(
        nodes_module,
        "ingest_campaign",
        _mock_ingest([], error=BudgetExceededError(org_id, 1.0, 10.0, 10.0)),
    )

    final_state = await run_pipeline(
        campaign_id, time.time(), pg_session_factory, fake_redis, use_checkpointer=False
    )

    assert final_state["terminal_reason"] == "SKIPPED_BUDGET"
    assert final_state.get("posts", []) == []

    async with pg_session_factory() as db:
        count = (await db.execute(text("SELECT count(*) FROM draft_replies"))).scalar_one()
        assert count == 0
        # A SystemLog row was written for the budget skip.
        rows = (
            await db.execute(
                text("SELECT message FROM system_logs WHERE org_id = :oid"), {"oid": org_id}
            )
        ).scalars().all()
        assert any("budget" in (m or "").lower() for m in rows)


# --- scout selects nothing -------------------------------------------------------


async def test_scout_returns_nothing_ends_the_run_with_no_drafts(pg_session_factory, fake_redis, monkeypatch):
    org_id, campaign_id = await _seed_org_and_campaign(pg_session_factory)
    posts = [_post("p1"), _post("p2")]

    monkeypatch.setattr(nodes_module, "ingest_campaign", _mock_ingest(posts))
    monkeypatch.setattr(nodes_module, "run_scout", _mock_scout([]))

    final_state = await run_pipeline(
        campaign_id, time.time(), pg_session_factory, fake_redis, use_checkpointer=False
    )

    assert final_state.get("selections", []) == []
    assert final_state.get("drafts", []) == []
    assert final_state.get("persisted_draft_ids", []) == []

    async with pg_session_factory() as db:
        count = (await db.execute(text("SELECT count(*) FROM draft_replies"))).scalar_one()
        assert count == 0


# --- dedup -----------------------------------------------------------------------


async def test_dedup_skips_a_post_with_an_existing_draft(pg_session_factory, fake_redis, monkeypatch):
    org_id, campaign_id = await _seed_org_and_campaign(pg_session_factory)
    posts = [_post("p1"), _post("p2")]

    async with pg_session_factory() as db:
        db.add(
            DraftReply(
                org_id=org_id,
                campaign_id=campaign_id,
                platform=PlatformEnum.REDDIT,
                post_id="p1",
                reply_type=ReplyType.NEW_COMMENT,
                status=DraftStatus.PENDING,
            )
        )
        await db.commit()

    monkeypatch.setattr(nodes_module, "ingest_campaign", _mock_ingest(posts))
    monkeypatch.setattr(
        nodes_module,
        "run_scout",
        _mock_scout(
            [
                ScoutSelection(post_id="p1", angle_name=ANGLE_NAME, confidence=0.9, reasoning="x"),
                ScoutSelection(post_id="p2", angle_name=ANGLE_NAME, confidence=0.9, reasoning="x"),
            ]
        ),
    )
    monkeypatch.setattr(nodes_module, "run_strategist_batch", _mock_strategist_batch())

    final_state = await run_pipeline(
        campaign_id, time.time(), pg_session_factory, fake_redis, use_checkpointer=False
    )

    # p1 was dropped in prefilter (duplicate_draft); only p2 reaches scout/strategist.
    assert [p["post_id"] for p in final_state["posts"]] == ["p2"]
    dedup_drops = [d for d in final_state["dropped"] if d["post_id"] == "p1"]
    assert dedup_drops and dedup_drops[0]["reason"] == "duplicate_draft"

    async with pg_session_factory() as db:
        post_ids = (await db.execute(text("SELECT post_id FROM draft_replies ORDER BY post_id"))).scalars().all()
        assert post_ids == ["p1", "p2"]


# --- daily caps ------------------------------------------------------------------


async def test_campaign_daily_cap_limits_how_many_posts_survive_prefilter(pg_session_factory, fake_redis, monkeypatch):
    org_id, campaign_id = await _seed_org_and_campaign(pg_session_factory, daily_draft_cap=1)
    posts = [_post("p1"), _post("p2"), _post("p3")]

    monkeypatch.setattr(nodes_module, "ingest_campaign", _mock_ingest(posts))
    monkeypatch.setattr(
        nodes_module,
        "run_scout",
        _mock_scout(
            [ScoutSelection(post_id=pid, angle_name=ANGLE_NAME, confidence=0.9, reasoning="x") for pid in ("p1", "p2", "p3")]
        ),
    )
    monkeypatch.setattr(nodes_module, "run_strategist_batch", _mock_strategist_batch())

    final_state = await run_pipeline(
        campaign_id, time.time(), pg_session_factory, fake_redis, use_checkpointer=False
    )

    assert len(final_state["posts"]) == 1
    cap_drops = [d for d in final_state["dropped"] if d["reason"] == "campaign_daily_cap"]
    assert len(cap_drops) == 2
    assert len(final_state["persisted_draft_ids"]) == 1


async def test_subreddit_safety_profile_cap_is_the_stricter_limit(pg_session_factory, fake_redis, monkeypatch):
    org_id, campaign_id = await _seed_org_and_campaign(pg_session_factory, daily_draft_cap=10)
    async with pg_session_factory() as db:
        db.add(
            SubredditSafetyProfile(
                org_id=org_id, subreddit="LLMDevs", max_daily_drafts=1, require_manual_review=True
            )
        )
        await db.commit()

    posts = [_post("p1"), _post("p2")]
    monkeypatch.setattr(nodes_module, "ingest_campaign", _mock_ingest(posts))
    monkeypatch.setattr(
        nodes_module,
        "run_scout",
        _mock_scout(
            [ScoutSelection(post_id=pid, angle_name=ANGLE_NAME, confidence=0.9, reasoning="x") for pid in ("p1", "p2")]
        ),
    )
    monkeypatch.setattr(nodes_module, "run_strategist_batch", _mock_strategist_batch())

    final_state = await run_pipeline(
        campaign_id, time.time(), pg_session_factory, fake_redis, use_checkpointer=False
    )

    assert len(final_state["posts"]) == 1
    cap_drops = [d for d in final_state["dropped"] if d["reason"] == "subreddit_daily_cap"]
    assert len(cap_drops) == 1


# --- checkpoint resume (real AsyncPostgresSaver) --------------------------------


async def test_checkpoint_resume_does_not_re_ingest_after_a_mid_run_crash(
    pg_session_factory, fake_redis, monkeypatch
):
    """PRD V7 §5.2/§5.3 AC: kill a worker mid-strategist -> restart -> the
    pipeline completes with zero additional ingestion calls."""
    await setup_checkpointer_tables(database_url=TEST_DATABASE_URL)

    org_id, campaign_id = await _seed_org_and_campaign(pg_session_factory)
    posts = [_post("p1")]

    ingest_calls = {"n": 0}
    monkeypatch.setattr(nodes_module, "ingest_campaign", _mock_ingest(posts, call_counter=ingest_calls))
    monkeypatch.setattr(
        nodes_module,
        "run_scout",
        _mock_scout([ScoutSelection(post_id="p1", angle_name=ANGLE_NAME, confidence=0.9, reasoning="x")]),
    )
    monkeypatch.setattr(nodes_module, "run_strategist_batch", _mock_strategist_batch())

    # Simulate "the worker died mid-strategist": finalize_draft (called from
    # inside finalize_node, right after strategist) raises exactly once.
    real_finalize_draft = nodes_module.finalize_draft
    crash_state = {"raised": False}

    def _crash_once(text, hook):
        if not crash_state["raised"]:
            crash_state["raised"] = True
            raise RuntimeError("simulated worker crash mid-pipeline")
        return real_finalize_draft(text, hook)

    monkeypatch.setattr(nodes_module, "finalize_draft", _crash_once)

    scheduled_ts = time.time()
    with pytest.raises(RuntimeError, match="simulated worker crash"):
        await run_pipeline(
            campaign_id, scheduled_ts, pg_session_factory, fake_redis,
            use_checkpointer=True, database_url=TEST_DATABASE_URL,
        )

    assert ingest_calls["n"] == 1

    # Retry: same (campaign_id, scheduled_ts) -> same checkpoint thread_id.
    final_state = await run_pipeline(
        campaign_id, scheduled_ts, pg_session_factory, fake_redis,
        use_checkpointer=True, database_url=TEST_DATABASE_URL,
    )

    assert ingest_calls["n"] == 1, "ingest must not run again on resume"
    assert len(final_state["persisted_draft_ids"]) == 1

    async with pg_session_factory() as db:
        draft = await db.get(DraftReply, final_state["persisted_draft_ids"][0])
        assert draft.status == DraftStatus.PENDING


# --- top-performing-angles hint (outcomes feedback loop, PRD §5.7) -------------


async def test_top_angles_hint_is_empty_with_no_outcomes(pg_session_factory):
    org_id, _campaign_id = await _seed_org_and_campaign(pg_session_factory)
    async with pg_session_factory() as db:
        hint = await get_top_angles_hint(db, org_id, "REDDIT")
    assert hint == ""


async def test_top_angles_hint_ranks_by_response_rate_and_caps_at_three(pg_session_factory):
    org_id, campaign_id = await _seed_org_and_campaign(pg_session_factory)

    async def _posted_draft(db, post_id, angle_name):
        draft = DraftReply(
            org_id=org_id,
            campaign_id=campaign_id,
            platform=PlatformEnum.REDDIT,
            post_id=post_id,
            reply_type=ReplyType.NEW_COMMENT,
            status=DraftStatus.POSTED,
            angle_name=angle_name,
        )
        db.add(draft)
        await db.flush()
        return draft

    # Four angles with four STRICTLY distinct response rates (no ties, so
    # the top-3 cutoff is deterministic) -- only the top 3 should make it
    # into the hint, in best-first order.
    async with pg_session_factory() as db:
        best = await _posted_draft(db, "p-best", "REDDIT-ANGLE-1: Best")  # 1/1 = 1.0
        mid = await _posted_draft(db, "p-mid", "REDDIT-ANGLE-2: Mid")  # 1/2 = 0.5
        low = await _posted_draft(db, "p-low", "REDDIT-ANGLE-3: Low")  # 1/3 = 0.33
        worst = await _posted_draft(db, "p-worst", "REDDIT-ANGLE-4: Worst")  # 0/1 = 0.0

        db.add(EngagementOutcome(draft_id=best.id, hours_after=24, got_response=True))
        db.add(EngagementOutcome(draft_id=mid.id, hours_after=24, got_response=True))
        db.add(EngagementOutcome(draft_id=mid.id, hours_after=72, got_response=False))
        db.add(EngagementOutcome(draft_id=low.id, hours_after=24, got_response=True))
        db.add(EngagementOutcome(draft_id=low.id, hours_after=48, got_response=False))
        db.add(EngagementOutcome(draft_id=low.id, hours_after=72, got_response=False))
        db.add(EngagementOutcome(draft_id=worst.id, hours_after=24, got_response=False))
        await db.commit()

    async with pg_session_factory() as db:
        hint = await get_top_angles_hint(db, org_id, "REDDIT")

    assert hint.startswith("\n\nHINT:")
    assert "REDDIT-ANGLE-4: Worst" not in hint
    assert "REDDIT-ANGLE-1: Best" in hint
    # Best-first ordering: the highest response-rate angle appears before a
    # lower one.
    assert hint.index("REDDIT-ANGLE-1: Best") < hint.index("REDDIT-ANGLE-3: Low")


async def test_top_angles_hint_only_counts_posted_drafts(pg_session_factory):
    org_id, campaign_id = await _seed_org_and_campaign(pg_session_factory)

    async with pg_session_factory() as db:
        rejected = DraftReply(
            org_id=org_id,
            campaign_id=campaign_id,
            platform=PlatformEnum.REDDIT,
            post_id="p-rejected",
            reply_type=ReplyType.NEW_COMMENT,
            status=DraftStatus.REJECTED,
            angle_name="REDDIT-ANGLE-5: Rejected",
        )
        db.add(rejected)
        await db.flush()
        db.add(EngagementOutcome(draft_id=rejected.id, hours_after=24, got_response=True))
        await db.commit()

    async with pg_session_factory() as db:
        hint = await get_top_angles_hint(db, org_id, "REDDIT")

    assert hint == ""
