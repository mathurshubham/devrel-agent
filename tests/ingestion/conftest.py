"""Shared stubs for the ingestion unit tests.

These tests must run without a database, without Redis and without network
access, so the SQLAlchemy models are replaced with plain stand-ins matching the
attribute contract the ingestion layer codes against.
"""

import pytest


class FakeCampaign:
    """Stands in for ``backend.models.Campaign``."""

    def __init__(
        self,
        platform,
        value,
        *,
        id=1,
        org_id=1,
        name="test campaign",
        platform_config=None,
        poll_frequency_minutes=240,
        keywords=None,
    ):
        self.id = id
        self.org_id = org_id
        self.name = name
        self.platform = platform
        self.value = value
        self.platform_config = platform_config or {}
        self.poll_frequency_minutes = poll_frequency_minutes
        self.keywords = keywords or []


class FakeOrgSettings:
    """Stands in for ``backend.models.OrgSettings``."""

    def __init__(
        self,
        *,
        apify_monthly_budget_usd=25.0,
        actor_overrides=None,
        linkedin_stale_days=None,
        linkedin_stale_min_engagement=None,
    ):
        self.apify_monthly_budget_usd = apify_monthly_budget_usd
        self.actor_overrides = actor_overrides or {}
        self.linkedin_stale_days = linkedin_stale_days
        self.linkedin_stale_min_engagement = linkedin_stale_min_engagement


class FakeRedis:
    """Minimal async Redis stand-in covering the calls the layer makes."""

    def __init__(self, initial=None):
        self.store = dict(initial or {})
        self.expirations = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, **kwargs):
        self.store[key] = value
        if ex:
            self.expirations[key] = ex
        return True

    async def delete(self, key):
        return int(self.store.pop(key, None) is not None)

    async def incrbyfloat(self, key, amount):
        total = float(self.store.get(key, 0.0)) + float(amount)
        self.store[key] = total
        return total

    async def expire(self, key, seconds):
        self.expirations[key] = seconds
        return True


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def campaign():
    return FakeCampaign
