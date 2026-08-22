"""Router-level tests for /api/analytics -- dependency-override style, no
real DB or Redis."""

from backend.models import DraftReply, DraftStatus, EngagementOutcome, PlatformEnum
from backend.utils.redis_dep import get_redis
from backend.main import app
from tests.pipeline.conftest import FakeRedis


def _override_redis(fake_redis):
    async def _fake():
        return fake_redis

    app.dependency_overrides[get_redis] = _fake


async def test_summary_is_shape_consistent_when_org_has_no_drafts(client, fake_db):
    fake_db.queue_execute_result(scalars_all=[])  # drafts
    fake_db.queue_execute_result(scalar_one_or_none=None)  # llm_config
    fake_db.queue_execute_result(scalar_one_or_none=None)  # org_settings

    _override_redis(FakeRedis())
    try:
        async with client as ac:
            resp = await ac.get("/api/analytics/summary")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"] == {"drafted": 0, "posted": 0, "rejected": 0, "reject_reasons": {}}
    assert body["angle_leaderboard"] == []
    assert body["platform_performance"] == []
    assert body["spend"]["llm"]["daily_tokens"] == 0
    assert body["spend"]["apify"]["spent_usd"] == 0.0


async def test_summary_acceptance_rate_is_a_fraction_not_a_percentage(client, fake_db):
    """Contract check: angle/platform acceptance_rate must be 0-1 -- the
    frontend multiplies by 100 for display."""
    drafts = [
        DraftReply(id=1, org_id=1, campaign_id=1, platform=PlatformEnum.LINKEDIN, post_id="p1",
                    angle_name="Angle A", status=DraftStatus.POSTED),
        DraftReply(id=2, org_id=1, campaign_id=1, platform=PlatformEnum.LINKEDIN, post_id="p2",
                    angle_name="Angle A", status=DraftStatus.PENDING),
        DraftReply(id=3, org_id=1, campaign_id=1, platform=PlatformEnum.LINKEDIN, post_id="p3",
                    angle_name="Angle A", status=DraftStatus.PENDING),
        DraftReply(id=4, org_id=1, campaign_id=1, platform=PlatformEnum.LINKEDIN, post_id="p4",
                    angle_name="Angle A", status=DraftStatus.PENDING),
    ]
    fake_db.queue_execute_result(scalars_all=drafts)  # drafts
    fake_db.queue_execute_result(scalars_all=[])  # engagement outcomes
    fake_db.queue_execute_result(scalar_one_or_none=None)  # llm_config
    fake_db.queue_execute_result(scalar_one_or_none=None)  # org_settings

    _override_redis(FakeRedis())
    try:
        async with client as ac:
            resp = await ac.get("/api/analytics/summary")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    body = resp.json()
    angle_row = body["angle_leaderboard"][0]
    assert angle_row["drafted"] == 4
    assert angle_row["posted"] == 1
    assert angle_row["acceptance_rate"] == 0.25  # NOT 25 -- a fraction

    platform_row = body["platform_performance"][0]
    assert platform_row["acceptance_rate"] == 0.25


async def test_summary_averages_engagement_from_best_outcome_per_draft(client, fake_db):
    drafts = [
        DraftReply(id=1, org_id=1, campaign_id=1, platform=PlatformEnum.REDDIT, post_id="p1",
                    angle_name="Angle B", status=DraftStatus.POSTED),
    ]
    outcomes = [
        EngagementOutcome(id=1, draft_id=1, hours_after=24, reactions=2, replies=1, reposts=0, got_response=True),
        EngagementOutcome(id=2, draft_id=1, hours_after=72, reactions=10, replies=4, reposts=1, got_response=True),
    ]
    fake_db.queue_execute_result(scalars_all=drafts)
    fake_db.queue_execute_result(scalars_all=outcomes)
    fake_db.queue_execute_result(scalar_one_or_none=None)
    fake_db.queue_execute_result(scalar_one_or_none=None)

    _override_redis(FakeRedis())
    try:
        async with client as ac:
            resp = await ac.get("/api/analytics/summary")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    angle_row = resp.json()["angle_leaderboard"][0]
    # Only the +72h capture (the later one) counts -- 10 + 4 + 1 = 15.
    assert angle_row["avg_engagement"] == 15.0


async def test_summary_rejects_are_bucketed_by_reason(client, fake_db):
    drafts = [
        DraftReply(id=1, org_id=1, campaign_id=1, platform=PlatformEnum.LINKEDIN, post_id="p1",
                    status=DraftStatus.REJECTED, reject_reason="off-tone"),
        DraftReply(id=2, org_id=1, campaign_id=1, platform=PlatformEnum.LINKEDIN, post_id="p2",
                    status=DraftStatus.REJECTED, reject_reason="off-tone"),
        DraftReply(id=3, org_id=1, campaign_id=1, platform=PlatformEnum.LINKEDIN, post_id="p3",
                    status=DraftStatus.REJECTED, reject_reason="factual"),
    ]
    fake_db.queue_execute_result(scalars_all=drafts)
    fake_db.queue_execute_result(scalar_one_or_none=None)
    fake_db.queue_execute_result(scalar_one_or_none=None)

    _override_redis(FakeRedis())
    try:
        async with client as ac:
            resp = await ac.get("/api/analytics/summary")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert resp.json()["totals"]["reject_reasons"] == {"off-tone": 2, "factual": 1}


async def test_top_angles_endpoint_delegates_to_top_angles_helper(client, monkeypatch):
    async def _fake_top_angles(db, org_id, platform, *, limit=3):
        assert platform == "LINKEDIN"
        return [("Angle A", 0.8), ("Angle B", 0.4)]

    monkeypatch.setattr("backend.api.analytics.top_angles", _fake_top_angles)

    async with client as ac:
        resp = await ac.get("/api/analytics/top-angles", params={"platform": "LINKEDIN"})

    assert resp.status_code == 200
    assert resp.json() == [{"angle": "Angle A", "response_rate": 0.8}, {"angle": "Angle B", "response_rate": 0.4}]
