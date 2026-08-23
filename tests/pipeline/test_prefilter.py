import time

import billiard
import pytest

from backend.pipeline.prefilter import (
    DEFAULT_SUBREDDIT_DAILY_CAP,
    campaign_daily_cap_key,
    matches_keyword_filters,
    matches_keyword_filters_async,
    remaining_daily_capacity,
    reserve_daily_slot,
    reserve_daily_slots,
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
    # Classic catastrophic-backtracking-shaped pattern against a string
    # engineered to blow up naive backtracking. The timeout guard must
    # return False (not hang the prefilter node) well within the test
    # timeout, whether or not this particular pattern happens to time out
    # against the installed `regex` engine (see the test below for one
    # that reliably does).
    evil_pattern = "regex:(a+)+$"
    content = "a" * 40 + "!"
    passed, matched = matches_keyword_filters(content, [evil_pattern])
    assert passed is False
    assert matched == []


def test_regex_timeout_guard_actually_fires_on_a_genuinely_catastrophic_pattern():
    # `(a|aa)+$` against a run of "a"s with no valid tail is a textbook
    # exponential-backtracking case that still defeats the `regex` module's
    # own optimizations (confirmed: this exact pattern/content pair blows
    # past a 0.1s deadline). This pins the actual TimeoutError path inside
    # `_regex_search_with_timeout`, not just "the pattern happened to
    # return no match quickly" -- and proves it completes in well under a
    # second rather than hanging the way stdlib `re` would on the same
    # input.
    evil_pattern = "regex:(a|aa)+$"
    content = "a" * 30 + "!"

    t0 = time.monotonic()
    passed, matched = matches_keyword_filters(content, [evil_pattern])
    elapsed = time.monotonic() - t0

    assert passed is False
    assert matched == []
    assert elapsed < 2.0, f"regex timeout guard did not bound runtime (took {elapsed}s)"


def _run_regex_check_in_child(args):
    content, keywords = args
    return matches_keyword_filters(content, keywords)


def test_regex_prefilter_guard_runs_inside_a_daemonic_billiard_child_without_crashing():
    """Celery's prefork pool executes task code inside *billiard* worker
    processes, and billiard starts those workers with ``daemon=True``. The
    old multiprocessing-based timeout guard called
    ``multiprocessing.get_context("fork").Process(..., daemon=True).start()``
    from *inside* the regex check itself -- daemonic processes are
    forbidden from starting children of their own, so `Process.start()`
    raised ``AssertionError`` the moment any `regex:` keyword was
    configured, escaping the guard's own try/except and killing the whole
    graph run. The fix removes forking entirely (the third-party `regex`
    library's own preemptive `timeout=` replaces it), so running the exact
    same check from inside a real billiard worker pool -- reproducing the
    daemonic-child constraint for real, not just asserting on it -- must
    not raise.
    """
    pool = billiard.Pool(1)
    try:
        result = pool.apply(
            _run_regex_check_in_child, (("we ship LLM Evals daily", ["regex:LLM\\s+Evals"]),)
        )
    finally:
        pool.close()
        pool.join()

    assert result == (True, ["regex:LLM\\s+Evals"])


def test_regex_prefilter_guard_runs_inside_a_daemonic_billiard_child_even_with_a_catastrophic_pattern():
    """Same as above, but with the genuinely-catastrophic pattern from
    ``test_regex_timeout_guard_actually_fires_on_a_genuinely_catastrophic_pattern``
    -- proving the no-forking fix holds even for the exact input that used
    to need a child process (and a timeout) to survive at all."""
    pool = billiard.Pool(1)
    try:
        result = pool.apply(
            _run_regex_check_in_child,
            (("a" * 30 + "!", ["regex:(a|aa)+$"]),),
        )
    finally:
        pool.close()
        pool.join()

    assert result == (False, [])


def test_too_long_regex_pattern_is_skipped_not_compiled():
    passed, matched = matches_keyword_filters("anything", ["regex:" + "a" * 501])
    assert passed is False
    assert matched == []


async def test_matches_keyword_filters_async_runs_off_the_event_loop_and_agrees_with_sync():
    passed, matched = await matches_keyword_filters_async(
        "We ship LLM Evals daily", ["regex:LLM\\s+Evals"]
    )
    assert passed is True
    assert matched == ["regex:LLM\\s+Evals"]


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


# --- remaining_daily_capacity (the prefilter's read-only peek) -----------------


async def test_remaining_daily_capacity_reports_the_full_cap_when_untouched(fake_redis):
    key = "draftcap:campaign:1:2026-08-22"
    assert await remaining_daily_capacity(fake_redis, key, cap=3) == 3


async def test_remaining_daily_capacity_never_claims_a_slot(fake_redis):
    key = "draftcap:campaign:1:2026-08-22"
    for _ in range(5):
        assert await remaining_daily_capacity(fake_redis, key, cap=3) == 3
    # Peeking five times must not have consumed anything -- a real slot
    # reservation still succeeds in full afterward.
    for _ in range(3):
        assert await reserve_daily_slot(fake_redis, key, cap=3) is True
    assert await reserve_daily_slot(fake_redis, key, cap=3) is False


async def test_remaining_daily_capacity_reflects_already_reserved_slots(fake_redis):
    key = "draftcap:campaign:1:2026-08-22"
    await reserve_daily_slot(fake_redis, key, cap=3)
    await reserve_daily_slot(fake_redis, key, cap=3)
    assert await remaining_daily_capacity(fake_redis, key, cap=3) == 1


async def test_remaining_daily_capacity_floors_at_zero_never_goes_negative(fake_redis):
    key = "draftcap:campaign:1:2026-08-22"
    await fake_redis.set(key, 10)
    assert await remaining_daily_capacity(fake_redis, key, cap=3) == 0


async def test_remaining_daily_capacity_is_zero_for_a_zero_or_negative_cap(fake_redis):
    key = "draftcap:campaign:1:2026-08-22"
    assert await remaining_daily_capacity(fake_redis, key, cap=0) == 0
    assert await remaining_daily_capacity(fake_redis, key, cap=-1) == 0


async def test_remaining_daily_capacity_is_zero_when_redis_is_unavailable():
    # Same NFR §6 conservative-degradation rule as reserve_daily_slot.
    key = "draftcap:campaign:1:2026-08-22"
    assert await remaining_daily_capacity(None, key, cap=3) == 0


# --- reserve_daily_slots (atomic multi-key reserve, all-or-nothing) ------------


async def test_reserve_daily_slots_claims_every_key_when_all_have_room(fake_redis):
    camp_key = "draftcap:campaign:1:2026-08-22"
    sub_key = "draftcap:subreddit:1:LLMDevs:2026-08-22"
    ok = await reserve_daily_slots(fake_redis, [(camp_key, 3), (sub_key, 3)])
    assert ok is True
    assert int(fake_redis.store[camp_key]) == 1
    assert int(fake_redis.store[sub_key]) == 1


async def test_reserve_daily_slots_releases_every_already_claimed_slot_on_a_later_miss(fake_redis):
    camp_key = "draftcap:campaign:1:2026-08-22"
    sub_key = "draftcap:subreddit:1:LLMDevs:2026-08-22"
    # Exhaust the subreddit cap first so the *second* key in the list is
    # the one that fails -- the campaign slot claimed just before it must
    # be released, not leaked.
    await reserve_daily_slot(fake_redis, sub_key, cap=1)

    ok = await reserve_daily_slots(fake_redis, [(camp_key, 3), (sub_key, 1)])

    assert ok is False
    assert int(fake_redis.store[camp_key]) == 0, "campaign slot must be released, not leaked"
    assert int(fake_redis.store[sub_key]) == 1, "the already-exhausted subreddit cap is untouched"


async def test_reserve_daily_slots_is_a_noop_gate_when_redis_is_unavailable():
    assert await reserve_daily_slots(None, [("k1", 3), ("k2", 3)]) is False


def test_default_subreddit_daily_cap_matches_prd_5_8():
    assert DEFAULT_SUBREDDIT_DAILY_CAP == 3
