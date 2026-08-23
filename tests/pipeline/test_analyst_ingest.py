import pytest

from backend.models import Competitor, PlatformEnum, TargetAuthor
from backend.pipeline import analyst_ingest
from backend.pipeline.analyst_ingest import (
    _author_pseudo_campaign,
    _competitor_pseudo_campaign,
    gather_analyst_posts,
)


def test_author_pseudo_campaign_builds_linkedin_profile_mode():
    author = TargetAuthor(org_id=1, name="Jane Doe", tier=1, profile_url="https://www.linkedin.com/in/jdoe")
    pseudo = _author_pseudo_campaign(1, author)
    assert pseudo is not None
    assert pseudo.platform == PlatformEnum.LINKEDIN
    assert pseudo.value == "https://www.linkedin.com/in/jdoe"
    assert pseudo.platform_config["mode"] == "profile"


def test_author_pseudo_campaign_none_without_profile_url():
    author = TargetAuthor(org_id=1, name="No URL", tier=1, profile_url=None)
    assert _author_pseudo_campaign(1, author) is None


def test_competitor_pseudo_campaign_detects_profile_mode():
    competitor = Competitor(org_id=1, name="Acme", url="https://www.linkedin.com/in/acme-founder")
    pseudo = _competitor_pseudo_campaign(1, competitor)
    assert pseudo.platform_config["mode"] == "profile"


def test_competitor_pseudo_campaign_detects_company_mode():
    competitor = Competitor(org_id=1, name="Acme", url="https://www.linkedin.com/company/acme")
    pseudo = _competitor_pseudo_campaign(1, competitor)
    assert pseudo.platform_config["mode"] == "company"


def test_competitor_pseudo_campaign_none_without_url():
    competitor = Competitor(org_id=1, name="Acme", url=None)
    assert _competitor_pseudo_campaign(1, competitor) is None


def test_competitor_pseudo_campaign_respects_explicit_platform():
    competitor = Competitor(org_id=1, name="Acme", url="acme", platform=PlatformEnum.TWITTER)
    pseudo = _competitor_pseudo_campaign(1, competitor)
    assert pseudo.platform == PlatformEnum.TWITTER
    assert "mode" not in pseudo.platform_config


class _FakeCampaign:
    def __init__(self, name):
        self.name = name


@pytest.fixture
def _sources(monkeypatch):
    """A single keyword campaign, one author, one competitor."""
    campaign = _FakeCampaign("kw-campaign")
    author = TargetAuthor(org_id=1, name="Author One", tier=2, profile_url="https://www.linkedin.com/in/a1")
    competitor = Competitor(org_id=1, name="Acme", url="https://www.linkedin.com/company/acme")

    async def _fake_sources_for_org(db, org_id):
        return [campaign], [author], [competitor]

    monkeypatch.setattr(analyst_ingest, "_sources_for_org", _fake_sources_for_org)
    return campaign, author, competitor


async def test_gather_analyst_posts_tags_competitor_posts_and_dedupes(monkeypatch, _sources):
    campaign, author, competitor = _sources

    async def _fake_ingest_campaign(db, pseudo, org_settings, tokens, *, redis_client=None):
        if pseudo is campaign:
            return [{"post_id": "p1", "platform": "LINKEDIN", "content": "hi"}]
        if pseudo.value == author.profile_url:
            # Same post re-surfaces via the author's own profile scrape.
            return [{"post_id": "p1", "platform": "LINKEDIN", "content": "hi"}]
        return [{"post_id": "c1", "platform": "LINKEDIN", "content": "competitor post"}]

    monkeypatch.setattr(analyst_ingest, "ingest_campaign", _fake_ingest_campaign)

    posts, competitor_posts, errors = await gather_analyst_posts(db=None, org_id=1, org_settings=None, vault_tokens=[])

    assert [p["post_id"] for p in posts] == ["p1"]  # deduped
    assert len(competitor_posts) == 1
    assert competitor_posts[0]["competitor"] == "Acme"
    assert errors == []


async def test_gather_analyst_posts_degrades_when_one_source_fails(monkeypatch, _sources):
    campaign, author, competitor = _sources

    async def _fake_ingest_campaign(db, pseudo, org_settings, tokens, *, redis_client=None):
        if pseudo is campaign:
            raise RuntimeError("apify blew up")
        if pseudo.value == author.profile_url:
            return [{"post_id": "p2", "platform": "LINKEDIN", "content": "author post"}]
        return []

    monkeypatch.setattr(analyst_ingest, "ingest_campaign", _fake_ingest_campaign)

    posts, competitor_posts, errors = await gather_analyst_posts(db=None, org_id=1, org_settings=None, vault_tokens=[])

    assert [p["post_id"] for p in posts] == ["p2"]
    assert len(errors) == 1
    assert "apify blew up" in errors[0]


async def test_gather_analyst_posts_degrades_on_budget_exceeded(monkeypatch, _sources):
    from backend.ingestion.service import BudgetExceededError

    async def _fake_ingest_campaign(db, pseudo, org_settings, tokens, *, redis_client=None):
        raise BudgetExceededError(1, 1.0, 10.0, 10.0)

    monkeypatch.setattr(analyst_ingest, "ingest_campaign", _fake_ingest_campaign)

    posts, competitor_posts, errors = await gather_analyst_posts(db=None, org_id=1, org_settings=None, vault_tokens=[])

    assert posts == []
    assert competitor_posts == []
    assert len(errors) == 3  # campaign + author + competitor all hit the same budget guard
