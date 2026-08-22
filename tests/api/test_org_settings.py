"""Router-level tests for GET/PATCH /api/org/settings."""

from backend.main import app
from backend.models import OrgSettings, User, UserRole
from backend.utils.auth import get_current_session
from tests.api.conftest import FAKE_SESSION


async def test_get_settings_returns_defaults_when_no_row_yet(client, fake_db):
    fake_db.queue_execute_result(scalar_one_or_none=None)

    async with client as ac:
        resp = await ac.get("/api/org/settings")

    assert resp.status_code == 200
    assert resp.json() == {
        "reply_hook": None,
        "scout_prompt": None,
        "linkedin_stale_days": None,
        "linkedin_stale_min_engagement": None,
        "analyst_enabled": False,
        "disclosure_reddit": True,
        "pillar_taxonomy": None,
        "apify_monthly_budget_usd": 50.0,
    }


async def test_get_settings_returns_existing_row(client, fake_db):
    existing = OrgSettings(
        id=1, org_id=1, reply_hook="Banner", scout_prompt="custom scout",
        linkedin_stale_days=30, linkedin_stale_min_engagement=5,
        analyst_enabled=True, disclosure_reddit=False,
        pillar_taxonomy=[{"tag": "CUSTOM", "tier": "PRIMARY"}],
        apify_monthly_budget_usd=75.0,
    )
    fake_db.queue_execute_result(scalar_one_or_none=existing)

    async with client as ac:
        resp = await ac.get("/api/org/settings")

    body = resp.json()
    assert body["reply_hook"] == "Banner"
    assert body["analyst_enabled"] is True
    assert body["disclosure_reddit"] is False
    assert body["pillar_taxonomy"] == [{"tag": "CUSTOM", "tier": "PRIMARY"}]
    assert body["apify_monthly_budget_usd"] == 75.0


async def test_patch_settings_403_for_member_role(client, fake_db):
    """PATCH controls real spend (apify_monthly_budget_usd) and feature
    opt-ins (analyst_enabled) -- a plain org MEMBER must not be able to
    change them."""
    async def _member_session():
        return {**FAKE_SESSION, "role": "MEMBER"}

    app.dependency_overrides[get_current_session] = _member_session

    async with client as ac:
        resp = await ac.patch("/api/org/settings", json={"analyst_enabled": True})

    assert resp.status_code == 403
    assert fake_db.committed == 0


async def test_patch_settings_allowed_for_platform_super_admin(client, fake_db):
    """A MEMBER-role org membership is still allowed through when the
    caller's own User row carries the platform SUPER_ADMIN role."""
    fake_db.added.append(User(id=1, clerk_user_id="user_test", email="x@example.com", role=UserRole.SUPER_ADMIN))
    existing = OrgSettings(
        id=1, org_id=1, reply_hook=None, scout_prompt=None,
        linkedin_stale_days=None, linkedin_stale_min_engagement=None,
        analyst_enabled=False, disclosure_reddit=True,
        pillar_taxonomy=None, apify_monthly_budget_usd=50.0,
    )
    fake_db.queue_execute_result(scalar_one_or_none=existing)

    async def _member_session():
        return {**FAKE_SESSION, "role": "MEMBER"}

    app.dependency_overrides[get_current_session] = _member_session

    async with client as ac:
        resp = await ac.patch("/api/org/settings", json={"analyst_enabled": True})

    assert resp.status_code == 200
    assert resp.json()["analyst_enabled"] is True


async def test_patch_settings_creates_row_on_first_write(client, fake_db):
    fake_db.queue_execute_result(scalar_one_or_none=None)  # no existing row

    payload = {
        "reply_hook": "Soft",
        "scout_prompt": "be selective",
        "linkedin_stale_days": 14,
        "linkedin_stale_min_engagement": 3,
        "analyst_enabled": True,
        "disclosure_reddit": False,
        "pillar_taxonomy": [{"tag": "CUSTOM_PILLAR", "tier": "PRIMARY"}],
        "apify_monthly_budget_usd": 100.0,
    }

    async with client as ac:
        resp = await ac.patch("/api/org/settings", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    for key, value in payload.items():
        assert body[key] == value
    assert fake_db.committed == 1


async def test_patch_settings_partial_update_leaves_other_fields_unchanged(client, fake_db):
    existing = OrgSettings(
        id=1, org_id=1, reply_hook="Banner", scout_prompt="original scout",
        linkedin_stale_days=30, linkedin_stale_min_engagement=5,
        analyst_enabled=False, disclosure_reddit=True,
        pillar_taxonomy=None, apify_monthly_budget_usd=50.0,
    )
    fake_db.queue_execute_result(scalar_one_or_none=existing)

    async with client as ac:
        resp = await ac.patch("/api/org/settings", json={"analyst_enabled": True})

    body = resp.json()
    assert body["analyst_enabled"] is True
    # Untouched fields survive the partial update.
    assert body["reply_hook"] == "Banner"
    assert body["scout_prompt"] == "original scout"
    assert body["apify_monthly_budget_usd"] == 50.0


async def test_patch_then_get_round_trip(client, fake_db):
    """A partial PATCH against an already-materialized row, then a
    subsequent GET, reflects the change -- the realistic "edit one field"
    flow (a brand-new row's un-submitted columns only pick up their
    SQLAlchemy column defaults on a real flush/INSERT, which this
    in-memory FakeDB doesn't simulate; see
    test_patch_settings_creates_row_on_first_write for that path)."""
    existing = OrgSettings(
        id=1, org_id=1, reply_hook=None, scout_prompt=None,
        linkedin_stale_days=None, linkedin_stale_min_engagement=None,
        analyst_enabled=False, disclosure_reddit=True,
        pillar_taxonomy=None, apify_monthly_budget_usd=50.0,
    )
    fake_db.queue_execute_result(scalar_one_or_none=existing)

    async with client as ac:
        patch_resp = await ac.patch(
            "/api/org/settings", json={"analyst_enabled": True, "apify_monthly_budget_usd": 42.0}
        )
        assert patch_resp.status_code == 200

        fake_db.queue_execute_result(scalar_one_or_none=existing)
        get_resp = await ac.get("/api/org/settings")

    assert get_resp.json()["analyst_enabled"] is True
    assert get_resp.json()["apify_monthly_budget_usd"] == 42.0
    assert get_resp.json()["disclosure_reddit"] is True  # untouched field survives
