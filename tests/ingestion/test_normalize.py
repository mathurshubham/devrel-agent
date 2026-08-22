"""Normalizer tests against realistic actor payloads, plus the stale filter."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.ingestion.normalize import (
    NormalizedPost,
    filter_stale_posts,
    normalize_items,
    normalize_linkedin,
    normalize_reddit,
    normalize_twitter,
    parse_linkedin_posted_at,
)

from tests.ingestion.fixtures import (
    LINKEDIN_ARTICLE_POST,
    LINKEDIN_JOB_POST,
    LINKEDIN_LEGACY_SHAPE_POST,
    LINKEDIN_SAMPLE,
    LINKEDIN_TEXT_POST,
    REDDIT_SAMPLE,
    TWITTER_SAMPLE,
)

CONTRACT_KEYS = set(NormalizedPost.model_fields)


def assert_matches_contract(post):
    assert set(post) == CONTRACT_KEYS
    assert isinstance(post["post_id"], str) and post["post_id"]
    assert isinstance(post["engagement_score"], int)
    assert post["posted_at"] is None or isinstance(post["posted_at"], str)


# --- LinkedIn ---------------------------------------------------------------


def test_linkedin_sample_produces_contract_shaped_posts():
    posts = normalize_linkedin(LINKEDIN_SAMPLE)

    for post in posts:
        assert_matches_contract(post)
        assert post["platform"] == "LINKEDIN"


def test_linkedin_job_posts_are_dropped():
    posts = normalize_linkedin(LINKEDIN_SAMPLE)
    assert LINKEDIN_JOB_POST["full_urn"] not in {p["post_id"] for p in posts}


def test_linkedin_items_without_any_id_are_dropped():
    assert normalize_linkedin([{"text": "no id here"}]) == []


def test_linkedin_apimaestro_shape_is_fully_mapped():
    post = normalize_linkedin([LINKEDIN_ARTICLE_POST])[0]

    assert post["post_id"] == "urn:li:ugcPost:7451013654352728064"
    assert post["author"] == "Shakun Vohra"
    assert post["author_name"] == "Shakun Vohra"
    assert post["author_headline"].startswith("AI Innovation Leader")
    assert post["author_profile_url"] == "https://www.linkedin.com/in/shakunvohra"
    assert post["content"].startswith("The $812 court case")
    assert post["url"] == LINKEDIN_ARTICLE_POST["post_url"]
    assert (post["reactions"], post["comments"], post["shares"]) == (25, 3, 1)
    assert post["engagement_score"] == 29
    assert post["posted_at"] == "2026-04-17T23:08:08+00:00"


def test_linkedin_bare_activity_id_is_promoted_to_a_full_urn():
    post = normalize_linkedin([LINKEDIN_LEGACY_SHAPE_POST])[0]
    assert post["post_id"] == "urn:li:activity:7400000000000000001"


def test_linkedin_flat_engagement_fields_are_understood():
    post = normalize_linkedin([LINKEDIN_LEGACY_SHAPE_POST])[0]
    assert (post["reactions"], post["comments"], post["shares"]) == (12, 4, 2)
    assert post["engagement_score"] == 18


def test_linkedin_bare_public_id_becomes_a_profile_url():
    post = normalize_linkedin([LINKEDIN_LEGACY_SHAPE_POST])[0]
    assert post["author_profile_url"] == "https://www.linkedin.com/in/dana-legacy"
    assert post["author"] == "Dana Legacy"
    assert post["author_headline"] == "Staff Engineer"


def test_linkedin_url_is_synthesised_when_the_actor_omits_it():
    post = normalize_linkedin([LINKEDIN_LEGACY_SHAPE_POST])[0]
    assert post["url"] == (
        "https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000001/"
    )


def test_linkedin_string_author_does_not_crash_the_normalizer():
    post = normalize_linkedin([{"id": "1", "author": "Just A Name", "text": "hi"}])[0]
    assert post["author"] == "Just A Name"
    assert post["author_headline"] == ""


def test_linkedin_content_falls_back_to_the_nested_content_text():
    post = normalize_linkedin(
        [{"id": "1", "author": {"name": "X"}, "content": {"type": "text", "text": "nested body"}}]
    )[0]
    assert post["content"] == "nested body"


def test_non_dict_items_are_ignored():
    assert normalize_linkedin(["a string", None, 42]) == []


# --- LinkedIn date parsing --------------------------------------------------


def test_posted_at_prefers_the_absolute_date_over_the_timestamp():
    assert parse_linkedin_posted_at(LINKEDIN_TEXT_POST) == "2026-04-16T05:18:18+00:00"


def test_posted_at_falls_back_to_the_epoch_millisecond_timestamp():
    parsed = parse_linkedin_posted_at({"posted_at": {"timestamp": 1776347613682}})
    assert parsed is not None
    assert parsed.startswith("2026-04-")


@pytest.mark.parametrize(
    "raw",
    [
        {"posted_at": {"display_text": "21m"}},
        {"posted_at": "3 weeks ago"},
        {"posted_at": None},
        {},
        {"posted_at": {"date": "not a date"}},
    ],
)
def test_relative_or_missing_dates_resolve_to_none(raw):
    assert parse_linkedin_posted_at(raw) is None


def test_posted_at_reads_flat_fallback_keys():
    assert parse_linkedin_posted_at({"createdAt": "2026-01-05"}) == "2026-01-05T00:00:00+00:00"
    assert parse_linkedin_posted_at({"time": "2026-01-05T10:00:00"}) == (
        "2026-01-05T10:00:00+00:00"
    )


def test_posted_at_handles_a_z_suffixed_iso_string():
    assert parse_linkedin_posted_at({"posted_at": "2026-01-05T10:00:00Z"}) == (
        "2026-01-05T10:00:00+00:00"
    )


# --- Reddit -----------------------------------------------------------------


def test_reddit_flat_stream_is_regrouped_into_posts_with_comments():
    posts = normalize_reddit(REDDIT_SAMPLE, subreddit="LLMDevs")

    assert [p["post_id"] for p in posts] == ["1abc234", "1def567"]
    for post in posts:
        assert_matches_contract(post)
        assert post["platform"] == "REDDIT"


def test_reddit_comments_are_attached_to_their_parent_post():
    post = normalize_reddit(REDDIT_SAMPLE, subreddit="LLMDevs")[0]

    assert [c["comment_id"] for c in post["top_comments"]] == ["c_001", "c_002"]
    first = post["top_comments"][0]
    assert first["author"] == "ragged_edge"
    assert first["content"].startswith("Golden set")
    assert first["score"] == 42
    assert first["url"] == "https://reddit.com/r/LLMDevs/comments/1abc234/comment/c_001/"


def test_reddit_orphan_comments_are_not_attached_anywhere():
    posts = normalize_reddit(REDDIT_SAMPLE, subreddit="LLMDevs")
    all_comment_ids = {c["comment_id"] for p in posts for c in p["top_comments"]}
    assert "c_003" not in all_comment_ids


def test_reddit_comment_count_is_capped():
    post = normalize_reddit(REDDIT_SAMPLE, subreddit="LLMDevs", max_comments=1)[0]
    assert len(post["top_comments"]) == 1


def test_reddit_posts_without_an_id_are_dropped():
    posts = normalize_reddit(REDDIT_SAMPLE, subreddit="LLMDevs")
    assert all(p["post_id"] for p in posts)
    assert len(posts) == 2


def test_reddit_empty_body_falls_back_to_a_placeholder():
    link_post = normalize_reddit(REDDIT_SAMPLE, subreddit="LLMDevs")[1]
    assert link_post["title"] == "Link post with no body"
    assert link_post["content"] == "Link post with no body"


def test_reddit_engagement_combines_upvotes_and_comment_count():
    post = normalize_reddit(REDDIT_SAMPLE, subreddit="LLMDevs")[0]
    assert post["reactions"] == 128
    assert post["comments"] == 2
    assert post["engagement_score"] == 130


def test_reddit_posted_at_is_parsed_from_the_iso_timestamp():
    post = normalize_reddit(REDDIT_SAMPLE, subreddit="LLMDevs")[0]
    assert post["posted_at"] == "2026-08-01T12:00:00+00:00"


# --- Twitter ----------------------------------------------------------------


def test_twitter_sample_maps_the_kaitoeasyapi_shape():
    posts = normalize_twitter(TWITTER_SAMPLE)

    assert len(posts) == 2
    for post in posts:
        assert_matches_contract(post)
        assert post["platform"] == "TWITTER"

    first = posts[0]
    assert first["post_id"] == "1799999999999999999"
    assert first["author"] == "evalpilled"
    assert first["author_name"] == "Eval Pilled"
    assert first["author_headline"].startswith("Shipping LLM systems")
    assert first["author_profile_url"] == "https://twitter.com/evalpilled"
    assert first["content"].startswith("Hot take")
    assert (first["reactions"], first["comments"], first["shares"]) == (210, 18, 40)
    assert first["engagement_score"] == 268
    assert first["posted_at"] == "2026-08-05T14:21:09+00:00"


def test_twitter_snake_case_author_fields_are_understood():
    second = normalize_twitter(TWITTER_SAMPLE)[1]
    assert second["author"] == "ci_curious"
    assert second["author_name"] == "CI Curious"
    assert second["author_profile_url"] == "https://twitter.com/ci_curious"


def test_twitter_url_is_synthesised_when_absent():
    second = normalize_twitter(TWITTER_SAMPLE)[1]
    assert second["url"] == "https://twitter.com/i/web/status/1788888888888888888"


def test_twitter_items_without_an_id_are_dropped():
    assert normalize_twitter([{"text": "no id"}]) == []


def test_twitter_non_dict_author_does_not_crash():
    post = normalize_twitter([{"id": "1", "text": "hi", "author": "not a dict"}])[0]
    assert post["author"] == "Unknown"


# --- dispatch and validation ------------------------------------------------


def test_normalize_items_dispatches_by_platform():
    assert normalize_items("TWITTER", TWITTER_SAMPLE)
    assert normalize_items("linkedin", LINKEDIN_SAMPLE)
    assert normalize_items("REDDIT", REDDIT_SAMPLE, subreddit="LLMDevs")


def test_normalize_items_rejects_an_unknown_platform():
    with pytest.raises(ValueError):
        normalize_items("MASTODON", [])


def test_a_malformed_item_is_skipped_rather_than_raising(caplog):
    # A comment with a non-coercible score fails validation for that post only.
    items = [
        {"type": "post", "id": "good", "title": "fine", "author": "a"},
        {"type": "post", "id": "bad", "title": "also fine", "author": "b"},
        {"type": "comment", "id": "c1", "postId": "bad", "score": {"nope": 1}},
    ]
    posts = normalize_reddit(items, max_comments=5)

    # Both posts survive: the unparseable score coerces to 0 rather than failing.
    assert {p["post_id"] for p in posts} == {"good", "bad"}
    assert posts[1]["top_comments"][0]["score"] == 0


def test_validation_drops_a_post_whose_id_is_empty():
    assert normalize_twitter([{"id": "", "text": "empty id"}]) == []


# --- stale filter -----------------------------------------------------------


def _post(days_old=None, engagement=0, post_id="p"):
    posted_at = None
    if days_old is not None:
        posted_at = (
            datetime.now(timezone.utc) - timedelta(days=days_old)
        ).isoformat()
    return {"post_id": post_id, "posted_at": posted_at, "engagement_score": engagement}


def test_stale_filter_drops_old_and_quiet_posts():
    posts = [_post(days_old=30, engagement=1, post_id="old_quiet")]
    kept, dropped = filter_stale_posts(posts, stale_days=14, stale_min_engagement=10)

    assert kept == []
    assert dropped == 1


def test_stale_filter_keeps_old_but_popular_posts():
    posts = [_post(days_old=30, engagement=500, post_id="old_loud")]
    kept, dropped = filter_stale_posts(posts, stale_days=14, stale_min_engagement=10)

    assert [p["post_id"] for p in kept] == ["old_loud"]
    assert dropped == 0


def test_stale_filter_keeps_recent_posts_regardless_of_engagement():
    posts = [_post(days_old=1, engagement=0, post_id="new_quiet")]
    kept, dropped = filter_stale_posts(posts, stale_days=14, stale_min_engagement=10)

    assert len(kept) == 1
    assert dropped == 0


def test_stale_filter_keeps_posts_with_no_parseable_date():
    posts = [
        {"post_id": "no_date", "posted_at": None, "engagement_score": 0},
        {"post_id": "bad_date", "posted_at": "three weeks ago", "engagement_score": 0},
    ]
    kept, dropped = filter_stale_posts(posts, stale_days=1, stale_min_engagement=100)

    assert len(kept) == 2
    assert dropped == 0


@pytest.mark.parametrize(
    "stale_days,stale_min_engagement",
    [(None, 10), (0, 10), (14, None)],
)
def test_stale_filter_is_a_no_op_when_a_threshold_is_unset(stale_days, stale_min_engagement):
    posts = [_post(days_old=999, engagement=0)]
    kept, dropped = filter_stale_posts(posts, stale_days, stale_min_engagement)

    assert kept == posts
    assert dropped == 0


def test_stale_filter_with_zero_min_engagement_keeps_everything_with_any_engagement():
    posts = [_post(days_old=99, engagement=0, post_id="silent")]
    kept, dropped = filter_stale_posts(posts, stale_days=14, stale_min_engagement=0)

    # engagement 0 is not < 0, so the post is kept
    assert len(kept) == 1
    assert dropped == 0


def test_stale_filter_boundary_is_strictly_older_than():
    just_inside = _post(days_old=13.9, engagement=0, post_id="inside")
    just_outside = _post(days_old=14.1, engagement=0, post_id="outside")

    kept, dropped = filter_stale_posts(
        [just_inside, just_outside], stale_days=14, stale_min_engagement=10
    )

    assert [p["post_id"] for p in kept] == ["inside"]
    assert dropped == 1


def test_stale_filter_handles_naive_iso_timestamps():
    naive = (datetime.now(timezone.utc) - timedelta(days=60)).replace(tzinfo=None).isoformat()
    posts = [{"post_id": "naive", "posted_at": naive, "engagement_score": 0}]

    kept, dropped = filter_stale_posts(posts, stale_days=14, stale_min_engagement=10)

    assert kept == []
    assert dropped == 1
