"""Router-level tests for /api/analytics -- dependency-override style, no
real DB or Redis.

``/summary`` is computed as SQL-side GROUP BY aggregates now (not a full
DraftReply/EngagementOutcome table scan into Python -- see
backend/api/analytics.py), so these tests queue the *aggregated* rows each
query would return rather than full ORM objects. The call order is fixed:
totals (status, reject_reason, count) -> platform/angle counts (platform,
angle_name, status, count) -> engagement (platform, angle_name,
engagement_sum, engagement_n; POSTED only, already deduped to the latest
capture per draft) -> llm_config -> org_settings.
"""

from backend.models import DraftStatus, PlatformEnum
from backend.utils.redis_dep import get_redis
from backend.main import app
from tests.pipeline.conftest import FakeRedis


def _override_redis(fake_redis):
    async def _fake():
        return fake_redis

    app.dependency_overrides[get_redis] = _fake


def _queue_summary(fake_db, *, totals=(), counts=(), engagement=()):
    fake_db.queue_execute_result(scalars_all=list(totals))
    fake_db.queue_execute_result(scalars_all=list(counts))
    fake_db.queue_execute_result(scalars_all=list(engagement))
    fake_db.queue_execute_result(scalar_one_or_none=None)  # llm_config
    fake_db.queue_execute_result(scalar_one_or_none=None)  # org_settings


async def test_summary_is_shape_consistent_when_org_has_no_drafts(client, fake_db):
    _queue_summary(fake_db)

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


async def test_summary_422_for_days_out_of_bounds(client, fake_db):
    _override_redis(FakeRedis())
    try:
        async with client as ac:
            resp = await ac.get("/api/analytics/summary", params={"days": 400})
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert resp.status_code == 422


async def test_summary_acceptance_rate_is_a_fraction_not_a_percentage(client, fake_db):
    """Contract check: angle/platform acceptance_rate must be 0-1 -- the
    frontend multiplies by 100 for display."""
    _queue_summary(
        fake_db,
        totals=[(DraftStatus.POSTED, None, 1), (DraftStatus.PENDING, None, 3)],
        counts=[
            (PlatformEnum.LINKEDIN, "Angle A", DraftStatus.POSTED, 1),
            (PlatformEnum.LINKEDIN, "Angle A", DraftStatus.PENDING, 3),
        ],
    )

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
    """The engagement query already dedupes to the latest ``hours_after``
    capture per draft SQL-side (a window function -- see
    backend/api/analytics.py) -- the +72h capture (10+4+1=15) is what it
    would return for this one POSTED draft, not the +24h one (2+1+0=3)."""
    _queue_summary(
        fake_db,
        totals=[(DraftStatus.POSTED, None, 1)],
        counts=[(PlatformEnum.REDDIT, "Angle B", DraftStatus.POSTED, 1)],
        engagement=[(PlatformEnum.REDDIT, "Angle B", 15, 1)],
    )

    _override_redis(FakeRedis())
    try:
        async with client as ac:
            resp = await ac.get("/api/analytics/summary")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    angle_row = resp.json()["angle_leaderboard"][0]
    assert angle_row["avg_engagement"] == 15.0


async def test_summary_rejects_are_bucketed_by_reason(client, fake_db):
    _queue_summary(
        fake_db,
        totals=[(DraftStatus.REJECTED, "off-tone", 2), (DraftStatus.REJECTED, "factual", 1)],
        counts=[(PlatformEnum.LINKEDIN, None, DraftStatus.REJECTED, 3)],
    )

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


async def test_top_angles_endpoint_422_for_invalid_platform(client):
    async with client as ac:
        resp = await ac.get("/api/analytics/top-angles", params={"platform": "BOGUS"})
    assert resp.status_code == 422


async def test_top_angles_endpoint_422_for_limit_out_of_bounds(client):
    async with client as ac:
        too_high = await ac.get("/api/analytics/top-angles", params={"platform": "LINKEDIN", "limit": 51})
        too_low = await ac.get("/api/analytics/top-angles", params={"platform": "LINKEDIN", "limit": 0})

    assert too_high.status_code == 422
    assert too_low.status_code == 422
