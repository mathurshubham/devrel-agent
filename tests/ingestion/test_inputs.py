"""Input-builder and actor-registry tests."""

import pytest

from backend.ingestion.inputs import (
    DEFAULT_ACTORS,
    ActorKey,
    build_actor_input,
    build_linkedin_input,
    build_reddit_input,
    build_twitter_input,
    detect_linkedin_mode,
    resolve_actor,
)

from tests.ingestion.conftest import FakeCampaign, FakeOrgSettings


# --- actor registry ---------------------------------------------------------


def test_registry_holds_the_five_default_actors():
    assert set(DEFAULT_ACTORS) == {k.value for k in ActorKey}
    assert len(DEFAULT_ACTORS) == 5
    assert DEFAULT_ACTORS[ActorKey.REDDIT.value] == "automation-lab/reddit-scraper"
    assert DEFAULT_ACTORS[ActorKey.LINKEDIN_KEYWORD.value].startswith("apimaestro/")


def test_org_settings_can_override_a_single_actor():
    settings = FakeOrgSettings(actor_overrides={"reddit": "myorg/custom-reddit-scraper"})

    assert resolve_actor(ActorKey.REDDIT, settings) == "myorg/custom-reddit-scraper"
    # untouched keys keep the default
    assert resolve_actor(ActorKey.TWITTER, settings) == DEFAULT_ACTORS["twitter"]


@pytest.mark.parametrize("overrides", [None, {}, {"reddit": ""}, {"reddit": "   "}])
def test_blank_overrides_fall_back_to_the_default(overrides):
    settings = FakeOrgSettings(actor_overrides=overrides)
    assert resolve_actor(ActorKey.REDDIT, settings) == DEFAULT_ACTORS["reddit"]


def test_unknown_registry_key_is_rejected():
    with pytest.raises(ValueError):
        resolve_actor("mastodon")


# --- Reddit -----------------------------------------------------------------


def test_reddit_input_defaults():
    actor_input = build_reddit_input(FakeCampaign("REDDIT", "LLMDevs"))

    assert actor_input == {
        "urls": ["https://www.reddit.com/r/LLMDevs/"],
        "sort": "top",
        "timeFilter": "day",
        "maxPostsPerSource": 15,
        "includeComments": True,
        "maxCommentsPerPost": 5,
    }


@pytest.mark.parametrize("value", ["LLMDevs", "r/LLMDevs", "/r/LLMDevs/", "LLMDevs/"])
def test_reddit_accepts_every_way_of_writing_a_subreddit(value):
    actor_input = build_reddit_input(FakeCampaign("REDDIT", value))
    assert actor_input["urls"] == ["https://www.reddit.com/r/LLMDevs/"]


def test_reddit_platform_config_overrides_defaults():
    campaign = FakeCampaign(
        "REDDIT",
        "LLMDevs",
        platform_config={
            "sort": "new",
            "time_filter": "week",
            "max_posts_per_source": 50,
            "max_comments_per_post": 20,
        },
    )
    actor_input = build_reddit_input(campaign)

    assert actor_input["sort"] == "new"
    assert actor_input["timeFilter"] == "week"
    assert actor_input["maxPostsPerSource"] == 50
    assert actor_input["maxCommentsPerPost"] == 20
    assert actor_input["includeComments"] is True


# --- LinkedIn ---------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://www.linkedin.com/in/shakunvohra", "profile"),
        ("https://LinkedIn.com/IN/UpperCase", "profile"),
        ("https://www.linkedin.com/company/anthropic/", "company"),
        ("LLM evaluation", "keyword"),
        ("https://example.com/blog", "keyword"),
        ("", "keyword"),
    ],
)
def test_linkedin_mode_is_detected_from_the_campaign_value(value, expected):
    assert detect_linkedin_mode(value) == expected


def test_linkedin_profile_input():
    key, actor_input = build_linkedin_input(
        FakeCampaign("LINKEDIN", "https://www.linkedin.com/in/shakunvohra")
    )

    assert key == ActorKey.LINKEDIN_PROFILE.value
    assert actor_input == {
        "profileUrl": "https://www.linkedin.com/in/shakunvohra",
        "limit": 10,
    }


def test_linkedin_company_input_honours_a_custom_limit():
    key, actor_input = build_linkedin_input(
        FakeCampaign(
            "LINKEDIN",
            "https://www.linkedin.com/company/anthropic/",
            platform_config={"limit": 25},
        )
    )

    assert key == ActorKey.LINKEDIN_COMPANY.value
    assert actor_input == {
        "companyUrl": "https://www.linkedin.com/company/anthropic/",
        "limit": 25,
    }


def test_linkedin_keyword_input_defaults():
    key, actor_input = build_linkedin_input(FakeCampaign("LINKEDIN", "LLM evaluation"))

    assert key == ActorKey.LINKEDIN_KEYWORD.value
    assert actor_input == {
        "keyword": "LLM evaluation",
        "limit": 30,
        "sort_type": "date_posted",
        "page_number": 1,
    }


def test_exact_match_quotes_the_keyword():
    _key, actor_input = build_linkedin_input(
        FakeCampaign("LINKEDIN", "LLM evaluation", platform_config={"exact_match": True})
    )
    assert actor_input["keyword"] == '"LLM evaluation"'


def test_legacy_sort_value_date_is_migrated_to_date_posted():
    _key, actor_input = build_linkedin_input(
        FakeCampaign("LINKEDIN", "evals", platform_config={"sort_type": "date"})
    )
    assert actor_input["sort_type"] == "date_posted"


def test_optional_linkedin_filters_are_only_sent_when_set():
    plain = build_linkedin_input(FakeCampaign("LINKEDIN", "evals"))[1]
    assert "date_filter" not in plain
    assert "company_urns" not in plain

    filtered = build_linkedin_input(
        FakeCampaign(
            "LINKEDIN",
            "evals",
            platform_config={
                "date_filter": "past-week",
                "company_urns": ["urn:li:organization:1441"],
                "author_company_urns": ["urn:li:organization:99"],
                "author_industry_urns": ["urn:li:industry:4"],
                "author_job_title": "Developer Advocate",
                "member_urns": ["urn:li:member:7"],
                "company_urns_unused": "ignored",
            },
        )
    )[1]

    assert filtered["date_filter"] == "past-week"
    assert filtered["company_urns"] == ["urn:li:organization:1441"]
    assert filtered["author_job_title"] == "Developer Advocate"
    assert "company_urns_unused" not in filtered


def test_explicit_mode_in_platform_config_beats_autodetection():
    key, actor_input = build_linkedin_input(
        FakeCampaign(
            "LINKEDIN",
            "https://www.linkedin.com/in/someone",
            platform_config={"mode": "keyword"},
        )
    )
    assert key == ActorKey.LINKEDIN_KEYWORD.value
    assert actor_input["keyword"] == "https://www.linkedin.com/in/someone"


# --- Twitter ----------------------------------------------------------------


def test_twitter_input_defaults_to_the_actor_minimum():
    actor_input = build_twitter_input(FakeCampaign("TWITTER", "llm evals"))

    assert actor_input == {
        "searchTerms": ["llm evals"],
        "maxItems": 20,
        "queryType": "Latest",
    }


def test_twitter_max_items_never_drops_below_the_actor_floor():
    actor_input = build_twitter_input(
        FakeCampaign("TWITTER", "llm evals", platform_config={"limit": 5})
    )
    assert actor_input["maxItems"] == 20


def test_twitter_optional_knobs():
    actor_input = build_twitter_input(
        FakeCampaign(
            "TWITTER",
            "llm evals",
            platform_config={
                "limit": 100,
                "query_type": "Top",
                "lang": "en",
                "since_days": 7,
                "min_retweets": 5,
                "min_faves": 10,
                "min_replies": 2,
                "filter_blue_verified": True,
                "filter_media": True,
            },
        )
    )

    assert actor_input["maxItems"] == 100
    assert actor_input["queryType"] == "Top"
    assert actor_input["lang"] == "en"
    assert actor_input["min_retweets"] == 5
    assert actor_input["min_faves"] == 10
    assert actor_input["min_replies"] == 2
    assert actor_input["filter:blue_verified"] is True
    assert actor_input["filter:media"] is True
    assert "filter:has_engagement" not in actor_input
    assert int(actor_input["since_time"]) > 0


def test_zero_valued_twitter_thresholds_are_omitted():
    actor_input = build_twitter_input(
        FakeCampaign(
            "TWITTER",
            "llm evals",
            platform_config={"min_retweets": 0, "since_days": 0, "filter_media": False},
        )
    )

    assert "min_retweets" not in actor_input
    assert "since_time" not in actor_input
    assert "filter:media" not in actor_input


# --- dispatch ---------------------------------------------------------------


@pytest.mark.parametrize(
    "platform,value,expected_actor",
    [
        ("REDDIT", "LLMDevs", DEFAULT_ACTORS["reddit"]),
        ("TWITTER", "llm evals", DEFAULT_ACTORS["twitter"]),
        ("LINKEDIN", "llm evals", DEFAULT_ACTORS["linkedin_keyword"]),
        (
            "LINKEDIN",
            "https://www.linkedin.com/in/x",
            DEFAULT_ACTORS["linkedin_profile"],
        ),
        (
            "LINKEDIN",
            "https://www.linkedin.com/company/x/",
            DEFAULT_ACTORS["linkedin_company"],
        ),
    ],
)
def test_build_actor_input_resolves_the_right_actor(platform, value, expected_actor):
    actor_id, actor_input = build_actor_input(FakeCampaign(platform, value))

    assert actor_id == expected_actor
    assert actor_input


def test_build_actor_input_accepts_an_enum_like_platform():
    class PlatformEnum:
        value = "REDDIT"

    actor_id, _ = build_actor_input(FakeCampaign(PlatformEnum(), "LLMDevs"))
    assert actor_id == DEFAULT_ACTORS["reddit"]


def test_build_actor_input_rejects_an_unsupported_platform():
    with pytest.raises(ValueError, match="Unsupported campaign platform"):
        build_actor_input(FakeCampaign("MASTODON", "@someone@fosstodon.org"))
