"""Orchestration tests: cost model, budget guard, and the ingest flow."""

import pytest

from backend.ingestion.service import (
    BudgetExceededError,
    DEFAULT_COST_PER_1K_USD,
    check_budget,
    cost_per_1k,
    estimate_monthly_cost_usd,
    estimate_run_cost_usd,
    get_month_spend_usd,
    ingest_campaign,
    record_spend_usd,
    runs_per_month,
    spend_key,
)
from backend.ingestion.tokens import NoUsableTokenError, VaultToken

from tests.ingestion.conftest import FakeCampaign, FakeOrgSettings
from tests.ingestion.fixtures import LINKEDIN_SAMPLE, REDDIT_SAMPLE, TWITTER_SAMPLE


class StubTokenService:
    """Returns a fixed token without touching Apify."""

    def __init__(self, token=None, error=None):
        self.token = token or VaultToken(token="apify_api_stub", token_id=1, label="stub")
        self.error = error

    async def select_best_token(self, tokens, **kwargs):
        if self.error:
            raise self.error
        from backend.ingestion.tokens import ApifyCreditSummary

        summary = ApifyCreditSummary(
            token_id=self.token.token_id,
            label=self.token.label,
            used_usd=1.0,
            max_usd=5.0,
            remaining_usd=4.0,
            pct_used=20.0,
            usage_cycle_start=None,
            usage_cycle_end=None,
            is_usable=True,
        )
        return self.token, summary


class StubRunner:
    """Records the run it was asked to perform and replays canned items."""

    def __init__(self, items):
        self.items = items
        self.calls = []

    async def run_actor(self, actor_id, actor_input):
        self.calls.append((actor_id, actor_input))
        return self.items


# --- cost model -------------------------------------------------------------


def test_default_cost_table_matches_the_prd():
    assert DEFAULT_COST_PER_1K_USD == {"LINKEDIN": 5.00, "REDDIT": 4.04, "TWITTER": 0.25}


def test_cost_per_1k_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("APIFY_COST_PER_1K_TWITTER", "0.40")
    assert cost_per_1k("TWITTER") == 0.40


def test_non_numeric_env_override_is_ignored(monkeypatch):
    monkeypatch.setenv("APIFY_COST_PER_1K_REDDIT", "free please")
    assert cost_per_1k("REDDIT") == 4.04


def test_unknown_platform_costs_nothing():
    assert cost_per_1k("MASTODON") == 0.0


def test_run_cost_scales_with_the_requested_result_count():
    small = FakeCampaign("LINKEDIN", "evals", platform_config={"limit": 30})
    large = FakeCampaign("LINKEDIN", "evals", platform_config={"limit": 300})

    assert estimate_run_cost_usd(small) == pytest.approx(0.15)
    assert estimate_run_cost_usd(large) == pytest.approx(1.50)


def test_reddit_run_cost_uses_max_posts_per_source():
    campaign = FakeCampaign(
        "REDDIT", "LLMDevs", platform_config={"max_posts_per_source": 100}
    )
    assert estimate_run_cost_usd(campaign) == pytest.approx(0.404)


def test_twitter_run_cost_respects_the_actor_floor():
    campaign = FakeCampaign("TWITTER", "evals", platform_config={"limit": 5})
    # floor of 20 items, 0.25 per 1k
    assert estimate_run_cost_usd(campaign) == pytest.approx(0.005)


def test_runs_per_month_derives_from_the_poll_frequency():
    assert runs_per_month(FakeCampaign("REDDIT", "a", poll_frequency_minutes=60)) == 720
    assert runs_per_month(FakeCampaign("REDDIT", "a", poll_frequency_minutes=1440)) == 30


def test_monthly_estimate_multiplies_run_cost_by_run_count():
    campaign = FakeCampaign(
        "TWITTER", "evals", platform_config={"limit": 100}, poll_frequency_minutes=1440
    )
    # 100 items * 0.25/1k = 0.025 per run, 30 runs a month
    assert estimate_monthly_cost_usd(campaign) == pytest.approx(0.75)


# --- spend counter ----------------------------------------------------------


def test_spend_key_is_scoped_to_org_and_month():
    from datetime import date

    assert spend_key(42, date(2026, 8, 22)) == "apify:spend:42:2026-08"


async def test_spend_starts_at_zero_and_accumulates(fake_redis):
    assert await get_month_spend_usd(1, fake_redis) == 0.0

    await record_spend_usd(1, 0.15, fake_redis)
    await record_spend_usd(1, 0.35, fake_redis)

    assert await get_month_spend_usd(1, fake_redis) == pytest.approx(0.50)
    assert fake_redis.expirations[spend_key(1)] > 0


async def test_spend_counters_do_not_bleed_between_orgs(fake_redis):
    await record_spend_usd(1, 5.0, fake_redis)
    assert await get_month_spend_usd(2, fake_redis) == 0.0


async def test_a_corrupt_counter_value_reads_as_zero(fake_redis):
    fake_redis.store[spend_key(1)] = "not a number"
    assert await get_month_spend_usd(1, fake_redis) == 0.0


# --- budget guard -----------------------------------------------------------


async def test_budget_check_passes_when_there_is_headroom(fake_redis):
    settings = FakeOrgSettings(apify_monthly_budget_usd=10.0)
    await record_spend_usd(1, 2.0, fake_redis)

    spent = await check_budget(1, 1.0, settings, fake_redis)

    assert spent == pytest.approx(2.0)


async def test_budget_check_raises_when_the_estimate_would_overshoot(fake_redis):
    settings = FakeOrgSettings(apify_monthly_budget_usd=10.0)
    await record_spend_usd(1, 9.8, fake_redis)

    with pytest.raises(BudgetExceededError) as excinfo:
        await check_budget(1, 0.5, settings, fake_redis)

    error = excinfo.value
    assert error.budget_usd == 10.0
    assert error.estimate_usd == 0.5
    assert error.spent_usd == pytest.approx(9.8)


async def test_a_missing_budget_setting_falls_back_to_the_default(fake_redis):
    settings = FakeOrgSettings(apify_monthly_budget_usd=None)
    assert await check_budget(1, 1.0, settings, fake_redis) == 0.0


# --- ingest_campaign --------------------------------------------------------


async def test_ingest_reddit_campaign_returns_normalized_posts(fake_redis):
    campaign = FakeCampaign("REDDIT", "LLMDevs", org_id=7)
    runner = StubRunner(REDDIT_SAMPLE)

    posts = await ingest_campaign(
        session=None,
        campaign=campaign,
        org_settings=FakeOrgSettings(),
        tokens=[],
        redis_client=fake_redis,
        token_service=StubTokenService(),
        runner=runner,
    )

    assert [p["post_id"] for p in posts] == ["1abc234", "1def567"]
    assert posts[0]["top_comments"]
    assert runner.calls[0][0] == "automation-lab/reddit-scraper"


async def test_ingest_twitter_campaign(fake_redis):
    posts = await ingest_campaign(
        session=None,
        campaign=FakeCampaign("TWITTER", "llm evals", org_id=7),
        org_settings=FakeOrgSettings(),
        tokens=[],
        redis_client=fake_redis,
        token_service=StubTokenService(),
        runner=StubRunner(TWITTER_SAMPLE),
    )

    assert len(posts) == 2
    assert all(p["platform"] == "TWITTER" for p in posts)


async def test_ingest_records_spend_only_after_the_run(fake_redis):
    campaign = FakeCampaign("REDDIT", "LLMDevs", org_id=7)

    assert await get_month_spend_usd(7, fake_redis) == 0.0
    await ingest_campaign(
        session=None,
        campaign=campaign,
        org_settings=FakeOrgSettings(),
        tokens=[],
        redis_client=fake_redis,
        token_service=StubTokenService(),
        runner=StubRunner(REDDIT_SAMPLE),
    )

    # 15 posts * 4.04 / 1000
    assert await get_month_spend_usd(7, fake_redis) == pytest.approx(0.0606)


async def test_ingest_refuses_to_run_when_the_budget_is_spent(fake_redis):
    campaign = FakeCampaign("LINKEDIN", "llm evals", org_id=7)
    runner = StubRunner(LINKEDIN_SAMPLE)
    await record_spend_usd(7, 9.95, fake_redis)

    with pytest.raises(BudgetExceededError):
        await ingest_campaign(
            session=None,
            campaign=campaign,
            org_settings=FakeOrgSettings(apify_monthly_budget_usd=10.0),
            tokens=[],
            redis_client=fake_redis,
            token_service=StubTokenService(),
            runner=runner,
        )

    assert runner.calls == [], "the actor must not start once the budget is gone"


async def test_ingest_propagates_a_dry_vault(fake_redis):
    with pytest.raises(NoUsableTokenError):
        await ingest_campaign(
            session=None,
            campaign=FakeCampaign("REDDIT", "LLMDevs", org_id=7),
            org_settings=FakeOrgSettings(),
            tokens=[],
            redis_client=fake_redis,
            token_service=StubTokenService(error=NoUsableTokenError([])),
            runner=StubRunner([]),
        )


async def test_ingest_applies_the_linkedin_stale_filter(fake_redis):
    # Every fixture post is well over a year old and quietly engaged.
    settings = FakeOrgSettings(
        linkedin_stale_days=7, linkedin_stale_min_engagement=1000
    )

    posts = await ingest_campaign(
        session=None,
        campaign=FakeCampaign("LINKEDIN", "llm evals", org_id=7),
        org_settings=settings,
        tokens=[],
        redis_client=fake_redis,
        token_service=StubTokenService(),
        runner=StubRunner(LINKEDIN_SAMPLE),
    )

    # Only the item whose date cannot be resolved survives.
    assert [p["post_id"] for p in posts] == ["urn:li:activity:7400000000000000001"]


async def test_ingest_without_the_stale_filter_keeps_every_post(fake_redis):
    posts = await ingest_campaign(
        session=None,
        campaign=FakeCampaign("LINKEDIN", "llm evals", org_id=7),
        org_settings=FakeOrgSettings(),
        tokens=[],
        redis_client=fake_redis,
        token_service=StubTokenService(),
        runner=StubRunner(LINKEDIN_SAMPLE),
    )

    assert len(posts) == 3  # job post and id-less item are dropped by the normalizer


async def test_ingest_uses_the_org_actor_override(fake_redis):
    runner = StubRunner([])
    settings = FakeOrgSettings(actor_overrides={"reddit": "myorg/private-reddit"})

    await ingest_campaign(
        session=None,
        campaign=FakeCampaign("REDDIT", "LLMDevs", org_id=7),
        org_settings=settings,
        tokens=[],
        redis_client=fake_redis,
        token_service=StubTokenService(),
        runner=runner,
    )

    assert runner.calls[0][0] == "myorg/private-reddit"
