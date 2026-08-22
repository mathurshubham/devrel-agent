"""Contract-locking integration tests for /api/analytics/summary and
/api/analyst/forecast against a REAL Postgres (+ Redis) instance.

Why this file exists: two frontend/backend contract drifts have shipped
because nothing asserted the *exact* response JSON keys these endpoints
return, and /api/analytics/summary's SQL -- a ``row_number() OVER`` window
function that picks the latest ``EngagementOutcome`` capture per draft --
has never actually run against a real database (sqlite/aiosqlite in the
rest of the suite doesn't exercise Postgres window functions faithfully).

Unlike tests/api/test_analytics_router.py (which stubs ``db.execute`` with
canned rows), this module drives the REAL FastAPI endpoints through
httpx's ``ASGITransport``, with the REAL SQLAlchemy/asyncpg session bound
to a throwaway Postgres, and REAL Redis for the spend meters. The ONLY
dependency override is auth (``get_current_session`` -> a fixed session
dict) -- everything else, including the window-function SQL, runs for
real.

Follows tests/test_postgres_integration.py's Docker-gated pattern:

    docker run --rm -d -p 55432:5432 -e POSTGRES_PASSWORD=test -e POSTGRES_DB=test postgres:15-alpine
    docker run --rm -d -p 56379:6379 redis:7-alpine

and optionally override TEST_DATABASE_URL / TEST_REDIS_URL. The whole
module is skipped (not failed) if neither is reachable.
"""
import os
import time
from datetime import date, datetime, timedelta, timezone

import pytest
import redis.asyncio as redis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import get_db
from backend.limiter import limiter
from backend.main import app
from backend.models import (
    AnalystRun,
    Base,
    Campaign,
    CampaignStatus,
    DraftReply,
    DraftStatus,
    EngagementOutcome,
    IntelBrief,
    Organization,
    PlatformEnum,
    ReplyType,
    TopicCluster,
)
from backend.pipeline.analyst_graph import current_week_of
from backend.utils.auth import get_current_session
from backend.utils.redis_dep import get_redis

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:test@localhost:55432/test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:56379/0")

FAKE_SESSION = {
    "org_id": None,  # filled in per-test once the seeded org exists
    "user_id": 1,
    "clerk_org_id": "org_contract_test",
    "clerk_user_id": "user_contract_test",
    "role": "ADMIN",
}


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
    """Fresh engine/schema per test, torn down afterward -- same shape as
    tests/test_postgres_integration.py's fixture of the same name."""
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


@pytest.fixture
async def api_client(pg_session_factory):
    """Real ASGI client for backend.main.app with dependency overrides for
    auth ONLY (get_current_session). ``get_db`` yields a session bound to
    the real test-Postgres engine; ``get_redis`` yields a real client
    bound to the real test-Redis instance -- both endpoints under test read
    live data/queries through them, nothing is mocked out."""

    async def _fake_session():
        return FAKE_SESSION

    async def _fake_db_dep():
        async with pg_session_factory() as session:
            yield session

    redis_client = redis.from_url(TEST_REDIS_URL)

    async def _fake_redis_dep():
        return redis_client

    app.dependency_overrides[get_current_session] = _fake_session
    app.dependency_overrides[get_db] = _fake_db_dep
    app.dependency_overrides[get_redis] = _fake_redis_dep

    previously_enabled = limiter.enabled
    limiter.enabled = False
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        limiter.enabled = previously_enabled
        app.dependency_overrides.clear()
        await redis_client.aclose()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_analytics_org(session_local):
    """A realistic org: 2 campaigns (REDDIT + LINKEDIN), 10 DraftReply rows
    spanning PENDING/POSTED/REJECTED with reject_reason + angle_name set,
    and EngagementOutcome rows including two captures (24h + 72h) for one
    draft -- the window-function case (the 72h capture must win).

    Numbers are chosen so every derived metric can be hand-verified:

    REDDIT / "TechDeepDive": 2 POSTED, 1 PENDING, 1 REJECTED(off-tone)
      -> drafted=4, posted=2, acceptance=0.5
      -> draft A: 24h capture (2+1+0=3) superseded by 72h (10+4+1=15)
      -> draft B: single 24h capture (5+2+1=8)
      -> engagement_sum=15+8=23, n=2, avg=11.5

    REDDIT / "CommunityStory": 1 POSTED (zero EngagementOutcome rows --
    division-by-zero-safe avg_engagement case), 1 REJECTED(factual_error)
      -> drafted=2, posted=1, acceptance=0.5, avg_engagement=0.0

    REDDIT totals: drafted=6, posted=3, rejected=2, acceptance=0.5,
      engagement_sum=23, n=2, avg=11.5

    LINKEDIN / "ThoughtLeadership": 1 POSTED (single 24h capture: 1+0+0=1),
    1 PENDING, 1 REJECTED(off-tone)
      -> drafted=3, posted=1, acceptance=1/3, avg_engagement=1.0

    LINKEDIN / "ProductUpdate": 1 PENDING, never posted (division-by-zero
    -safe acceptance_rate + avg_engagement case: posted=0, engagement_n=0)
      -> drafted=1, posted=0, acceptance=0.0, avg_engagement=0.0

    LINKEDIN totals: drafted=4, posted=1, rejected=1, acceptance=0.25,
      engagement_sum=1, n=1, avg=1.0

    Org totals: drafted=10, posted=4, rejected=3,
      reject_reasons={"off-tone": 2, "factual_error": 1}
    """
    now = datetime.now(timezone.utc)

    async with session_local() as db:
        org = Organization(
            clerk_org_id=FAKE_SESSION["clerk_org_id"], name="Contract Test Org", is_active=True
        )
        db.add(org)
        await db.flush()

        campaign_reddit = Campaign(
            org_id=org.id, platform=PlatformEnum.REDDIT, name="Reddit Campaign",
            status=CampaignStatus.ACTIVE, poll_frequency_minutes=240,
        )
        campaign_linkedin = Campaign(
            org_id=org.id, platform=PlatformEnum.LINKEDIN, name="LinkedIn Campaign",
            status=CampaignStatus.ACTIVE, poll_frequency_minutes=240,
        )
        db.add_all([campaign_reddit, campaign_linkedin])
        await db.flush()

        def _draft(*, campaign, platform, angle, status, post_id, reject_reason=None):
            return DraftReply(
                org_id=org.id,
                campaign_id=campaign.id,
                platform=platform,
                post_id=post_id,
                reply_type=ReplyType.NEW_COMMENT,
                angle_name=angle,
                status=status,
                reject_reason=reject_reason,
                created_at=now - timedelta(days=1),
                ai_draft_text="draft body",
            )

        draft_a = _draft(
            campaign=campaign_reddit, platform=PlatformEnum.REDDIT, angle="TechDeepDive",
            status=DraftStatus.POSTED, post_id="reddit-a",
        )
        draft_b = _draft(
            campaign=campaign_reddit, platform=PlatformEnum.REDDIT, angle="TechDeepDive",
            status=DraftStatus.POSTED, post_id="reddit-b",
        )
        draft_c = _draft(
            campaign=campaign_reddit, platform=PlatformEnum.REDDIT, angle="TechDeepDive",
            status=DraftStatus.PENDING, post_id="reddit-c",
        )
        draft_d = _draft(
            campaign=campaign_reddit, platform=PlatformEnum.REDDIT, angle="TechDeepDive",
            status=DraftStatus.REJECTED, post_id="reddit-d", reject_reason="off-tone",
        )
        draft_e = _draft(
            campaign=campaign_reddit, platform=PlatformEnum.REDDIT, angle="CommunityStory",
            status=DraftStatus.POSTED, post_id="reddit-e",
        )
        draft_f = _draft(
            campaign=campaign_reddit, platform=PlatformEnum.REDDIT, angle="CommunityStory",
            status=DraftStatus.REJECTED, post_id="reddit-f", reject_reason="factual_error",
        )
        draft_g = _draft(
            campaign=campaign_linkedin, platform=PlatformEnum.LINKEDIN, angle="ThoughtLeadership",
            status=DraftStatus.POSTED, post_id="linkedin-g",
        )
        draft_h = _draft(
            campaign=campaign_linkedin, platform=PlatformEnum.LINKEDIN, angle="ThoughtLeadership",
            status=DraftStatus.PENDING, post_id="linkedin-h",
        )
        draft_i = _draft(
            campaign=campaign_linkedin, platform=PlatformEnum.LINKEDIN, angle="ThoughtLeadership",
            status=DraftStatus.REJECTED, post_id="linkedin-i", reject_reason="off-tone",
        )
        draft_j = _draft(
            campaign=campaign_linkedin, platform=PlatformEnum.LINKEDIN, angle="ProductUpdate",
            status=DraftStatus.PENDING, post_id="linkedin-j",
        )

        db.add_all(
            [draft_a, draft_b, draft_c, draft_d, draft_e, draft_f, draft_g, draft_h, draft_i, draft_j]
        )
        await db.flush()

        outcomes = [
            # draft_a: TWO captures -- the window function must pick the 72h
            # one (15), not the 24h one (3).
            EngagementOutcome(draft_id=draft_a.id, hours_after=24, reactions=2, replies=1, reposts=0),
            EngagementOutcome(draft_id=draft_a.id, hours_after=72, reactions=10, replies=4, reposts=1),
            # draft_b: single capture (8).
            EngagementOutcome(draft_id=draft_b.id, hours_after=24, reactions=5, replies=2, reposts=1),
            # draft_e: POSTED but deliberately NO EngagementOutcome rows.
            # draft_g: single capture (1).
            EngagementOutcome(draft_id=draft_g.id, hours_after=24, reactions=1, replies=0, reposts=0),
        ]
        db.add_all(outcomes)
        await db.commit()

        return org.id


async def _seed_forecast_org(session_local, org_id):
    """AnalystRun + TopicCluster rows across 2 weeks (this Monday and the
    prior Monday) so /api/analyst/forecast has a trending, a declining,
    and a stable pillar to classify, plus a couple of IntelBrief rows for
    the same weeks (realistic seed, per the org's weekly cadence)."""
    this_monday = current_week_of()
    prev_monday = this_monday - timedelta(days=7)

    async with session_local() as db:
        run_prev = AnalystRun(
            org_id=org_id, week_of=prev_monday, status="COMPLETED",
            started_at=datetime.now(timezone.utc) - timedelta(days=8),
            finished_at=datetime.now(timezone.utc) - timedelta(days=8),
        )
        run_this = AnalystRun(
            org_id=org_id, week_of=this_monday, status="COMPLETED",
            started_at=datetime.now(timezone.utc) - timedelta(days=1),
            finished_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add_all([run_prev, run_this])
        await db.flush()

        clusters = [
            # PillarA: trending (2 -> 5, delta +3)
            TopicCluster(run_id=run_prev.id, pillar="PillarA", count=2),
            TopicCluster(run_id=run_this.id, pillar="PillarA", count=5),
            # PillarB: declining (5 -> 2, delta -3)
            TopicCluster(run_id=run_prev.id, pillar="PillarB", count=5),
            TopicCluster(run_id=run_this.id, pillar="PillarB", count=2),
            # PillarC: stable (3 -> 3)
            TopicCluster(run_id=run_prev.id, pillar="PillarC", count=3),
            TopicCluster(run_id=run_this.id, pillar="PillarC", count=3),
        ]
        db.add_all(clusters)

        briefs = [
            IntelBrief(org_id=org_id, week_of=prev_monday, content_md="# Week 1 brief\nPillarB was hot."),
            IntelBrief(org_id=org_id, week_of=this_monday, content_md="# Week 2 brief\nPillarA is rising."),
        ]
        db.add_all(briefs)
        await db.commit()

    return this_monday, prev_monday


# ---------------------------------------------------------------------------
# /api/analytics/summary
# ---------------------------------------------------------------------------


async def test_analytics_summary_locks_exact_shape_against_real_postgres(
    pg_session_factory, api_client
):
    org_id = await _seed_analytics_org(pg_session_factory)
    FAKE_SESSION["org_id"] = org_id

    resp = await api_client.get("/api/analytics/summary")
    assert resp.status_code == 200
    body = resp.json()

    # ── Exact top-level key set ─────────────────────────────────────────
    assert set(body.keys()) == {"totals", "angle_leaderboard", "platform_performance", "spend"}

    # ── totals ───────────────────────────────────────────────────────────
    assert set(body["totals"].keys()) == {"drafted", "posted", "rejected", "reject_reasons"}
    assert body["totals"]["drafted"] == 10
    assert body["totals"]["posted"] == 4
    assert body["totals"]["rejected"] == 3
    assert body["totals"]["reject_reasons"] == {"off-tone": 2, "factual_error": 1}

    # ── angle_leaderboard: exact row key set (incl. "angle") ───────────
    assert len(body["angle_leaderboard"]) == 4
    for row in body["angle_leaderboard"]:
        assert set(row.keys()) == {"platform", "angle", "drafted", "posted", "acceptance_rate", "avg_engagement"}

    by_angle = {(r["platform"], r["angle"]): r for r in body["angle_leaderboard"]}

    tech_deep_dive = by_angle[("REDDIT", "TechDeepDive")]
    assert tech_deep_dive["drafted"] == 4
    assert tech_deep_dive["posted"] == 2
    assert tech_deep_dive["acceptance_rate"] == 0.5
    # The window function must have picked the 72h capture (15) over the
    # 24h one (3) for draft_a -- avg((15+8)/2) == 11.5, not (3+8)/2 == 5.5.
    assert tech_deep_dive["avg_engagement"] == 11.5

    community_story = by_angle[("REDDIT", "CommunityStory")]
    assert community_story["drafted"] == 2
    assert community_story["posted"] == 1
    assert community_story["acceptance_rate"] == 0.5
    # POSTED but zero EngagementOutcome rows -- must be 0.0, not a
    # division-by-zero error.
    assert community_story["avg_engagement"] == 0.0

    thought_leadership = by_angle[("LINKEDIN", "ThoughtLeadership")]
    assert thought_leadership["drafted"] == 3
    assert thought_leadership["posted"] == 1
    assert thought_leadership["acceptance_rate"] == round(1 / 3, 2)
    assert thought_leadership["avg_engagement"] == 1.0

    product_update = by_angle[("LINKEDIN", "ProductUpdate")]
    assert product_update["drafted"] == 1
    assert product_update["posted"] == 0
    # Never posted -- acceptance_rate and avg_engagement must both be a
    # safe 0.0, not a ZeroDivisionError-triggered 500.
    assert product_update["acceptance_rate"] == 0.0
    assert product_update["avg_engagement"] == 0.0

    # acceptance_rate is a 0..1 fraction everywhere, never a 0..100 percentage.
    for row in body["angle_leaderboard"]:
        assert 0.0 <= row["acceptance_rate"] <= 1.0

    # ── platform_performance: exact row key set ─────────────────────────
    assert len(body["platform_performance"]) == 2
    for row in body["platform_performance"]:
        assert set(row.keys()) == {"platform", "drafted", "posted", "rejected", "acceptance_rate", "avg_engagement"}
        assert 0.0 <= row["acceptance_rate"] <= 1.0

    by_platform = {r["platform"]: r for r in body["platform_performance"]}

    reddit = by_platform["REDDIT"]
    assert reddit["drafted"] == 6
    assert reddit["posted"] == 3
    assert reddit["rejected"] == 2
    assert reddit["acceptance_rate"] == 0.5
    assert reddit["avg_engagement"] == 11.5

    linkedin = by_platform["LINKEDIN"]
    assert linkedin["drafted"] == 4
    assert linkedin["posted"] == 1
    assert linkedin["rejected"] == 1
    assert linkedin["acceptance_rate"] == 0.25
    assert linkedin["avg_engagement"] == 1.0

    # ── spend ────────────────────────────────────────────────────────────
    assert set(body["spend"].keys()) == {"llm", "apify"}
    assert set(body["spend"]["llm"].keys()) == {
        "daily_tokens", "monthly_cost_usd", "max_daily_tokens", "max_monthly_cost_usd",
    }
    assert set(body["spend"]["apify"].keys()) == {"month", "spent_usd", "budget_usd", "utilization_pct"}
    # No OrgLLMConfig / spend keys were seeded for this org -- these must
    # degrade to safe defaults, not error.
    assert body["spend"]["llm"]["daily_tokens"] == 0
    assert body["spend"]["llm"]["monthly_cost_usd"] == 0.0
    assert body["spend"]["llm"]["max_daily_tokens"] is None
    assert body["spend"]["llm"]["max_monthly_cost_usd"] is None
    assert body["spend"]["apify"]["spent_usd"] == 0.0
    assert body["spend"]["apify"]["utilization_pct"] == 0.0


# ---------------------------------------------------------------------------
# /api/analyst/forecast
# ---------------------------------------------------------------------------


async def test_analyst_forecast_locks_exact_shape_against_real_postgres(
    pg_session_factory, api_client
):
    org_id = await _seed_analytics_org(pg_session_factory)
    this_monday, prev_monday = await _seed_forecast_org(pg_session_factory, org_id)
    FAKE_SESSION["org_id"] = org_id

    resp = await api_client.get("/api/analyst/forecast")
    assert resp.status_code == 200
    body = resp.json()

    # ── Exact top-level key set ─────────────────────────────────────────
    assert set(body.keys()) == {"weeks_analyzed", "trending", "declining", "stable", "recommended_focus"}

    assert body["weeks_analyzed"] == [prev_monday.isoformat(), this_monday.isoformat()]

    # ── trending: exact row shape {pillar, series, delta} ──────────────
    assert len(body["trending"]) == 1
    trending_row = body["trending"][0]
    assert set(trending_row.keys()) == {"pillar", "series", "delta"}
    assert trending_row["pillar"] == "PillarA"
    assert trending_row["series"] == [2, 5]
    assert trending_row["delta"] == 3

    # ── declining: same row shape, negative delta, correct pillar ──────
    assert len(body["declining"]) == 1
    declining_row = body["declining"][0]
    assert set(declining_row.keys()) == {"pillar", "series", "delta"}
    assert declining_row["pillar"] == "PillarB"
    assert declining_row["series"] == [5, 2]
    assert declining_row["delta"] == -3

    # ── stable: no "delta" key (see backend/api/analyst.py) ────────────
    assert len(body["stable"]) == 1
    stable_row = body["stable"][0]
    assert set(stable_row.keys()) == {"pillar", "series"}
    assert stable_row["pillar"] == "PillarC"
    assert stable_row["series"] == [3, 3]

    assert body["recommended_focus"] == ["PillarA"]
