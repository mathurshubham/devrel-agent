import re

import pytest

from backend.pipeline.prefilter import (
    campaign_daily_cap_key,
    matches_keyword_filters,
    reserve_daily_slot,
    subreddit_daily_cap_key,
)


# --- matches_keyword_filters -------------------------------------------------


def test_no_keywords_means_no_filter():
    passed, matched = matches_keyword_filters("anything at all", [])
    assert passed is True
    assert matched == []


def test_substring_match_is_case_insensitive():
    passed, matched = matches_keyword_filters("We use LangGraph in prod", ["langgraph"])
    assert passed is True
    assert matched == ["langgraph"]


def test_substring_no_match():
    passed, matched = matches_keyword_filters("totally unrelated content", ["langgraph"])
    assert passed is False
    assert matched == []


def test_regex_prefix_is_compiled_and_matched_case_insensitively():
    passed, matched = matches_keyword_filters("We ship LLM Evals daily", ["regex:LLM\\s+Evals"])
    assert passed is True
    assert matched == ["regex:LLM\\s+Evals"]


def test_invalid_regex_is_skipped_not_raised():
    # Unbalanced parenthesis -- must not raise, must not match.
    passed, matched = matches_keyword_filters("some content", ["regex:("])
    assert passed is False
    assert matched == []


def test_multiple_keywords_any_match_passes():
    passed, matched = matches_keyword_filters("we talked about evals", ["nonexistent", "evals"])
    assert passed is True
    assert matched == ["evals"]


def test_regex_timeout_guard_treats_a_slow_pattern_as_no_match():
    # Classic catastrophic-backtracking pattern against a string engineered
    # to blow up naive backtracking. The timeout guard must return False
    # (not hang the prefilter node) well within the test timeout.
    evil_pattern = "regex:(a+)+$"
    content = "a" * 40 + "!"
    passed, matched = matches_keyword_filters(content, [evil_pattern])
    assert passed is False
    assert matched == []


# --- daily cap keys -----------------------------------------------------------


def test_campaign_daily_cap_key_is_scoped_to_campaign_and_day():
    assert campaign_daily_cap_key(42, "2026-08-22") == "draftcap:campaign:42:2026-08-22"


def test_subreddit_daily_cap_key_is_scoped_to_org_subreddit_and_day():
    assert (
        subreddit_daily_cap_key(7, "LLMDevs", "2026-08-22")
        == "draftcap:subreddit:7:LLMDevs:2026-08-22"
    )


# --- reserve_daily_slot ---------------------------------------------------------


async def test_reserve_daily_slot_allows_up_to_the_cap(fake_redis):
    key = "draftcap:campaign:1:2026-08-22"
    for _ in range(3):
        assert await reserve_daily_slot(fake_redis, key, cap=3) is True
    # The 4th reservation must be refused, and the counter must not keep growing.
    assert await reserve_daily_slot(fake_redis, key, cap=3) is False
    assert int(fake_redis.store[key]) == 3


async def test_reserve_daily_slot_sets_a_ttl_on_first_use(fake_redis):
    key = "draftcap:campaign:1:2026-08-22"
    await reserve_daily_slot(fake_redis, key, cap=5)
    assert fake_redis.expirations[key] > 0


async def test_reserve_daily_slot_refuses_a_zero_or_negative_cap(fake_redis):
    key = "draftcap:campaign:1:2026-08-22"
    assert await reserve_daily_slot(fake_redis, key, cap=0) is False
    assert await reserve_daily_slot(fake_redis, key, cap=-1) is False


async def test_reserve_daily_slot_is_conservative_when_redis_is_unavailable():
    key = "draftcap:campaign:1:2026-08-22"
    # NFR §6: a lost daily-draft counter must reset caps to safe defaults,
    # never to unlimited -- no Redis means "refuse", not "allow".
    assert await reserve_daily_slot(None, key, cap=3) is False


async def test_reserve_daily_slot_two_independent_campaigns_do_not_share_a_counter(fake_redis):
    key_a = campaign_daily_cap_key(1, "2026-08-22")
    key_b = campaign_daily_cap_key(2, "2026-08-22")
    for _ in range(3):
        assert await reserve_daily_slot(fake_redis, key_a, cap=3) is True
    # A different campaign's cap is untouched.
    assert await reserve_daily_slot(fake_redis, key_b, cap=1) is True
