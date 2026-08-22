"""Zero-LLM-cost prefilter helpers (PRD V7 §5.3 step 2).

Keyword/regex matching, and the Redis-backed daily draft caps (campaign-level
and, for Reddit, subreddit-level via ``SubredditSafetyProfile``). Dedup
against ``PostedHistory``/``DraftReply`` lives in ``backend.pipeline.nodes``
(it needs a DB session); everything here is pure or Redis-only so it is cheap
to unit test.
"""

from __future__ import annotations

import asyncio
import logging

import regex

logger = logging.getLogger(__name__)

#: Campaign-configured `regex:` prefilter keywords are user input running
#: against untrusted post content -- bound worst-case catastrophic
#: backtracking with a hard wall-clock timeout rather than trusting the
#: pattern. Kept short: this runs once per post per `regex:` keyword.
_REGEX_TIMEOUT_SECONDS = 0.1

#: Reject a `regex:` keyword longer than this before ever compiling it --
#: compiling itself is cheap, but this keeps a pasted-in-error multi-KB blob
#: from being treated as regex source at all.
_MAX_REGEX_PATTERN_LENGTH = 500

#: How long a daily-cap counter key lives -- long enough to survive a slow
#: day boundary, short enough not to accumulate forever.
DAILY_CAP_KEY_TTL_SECONDS = 60 * 60 * 24 * 2

#: PRD V7 §5.8: a subreddit with no explicit `SubredditSafetyProfile` row
#: still gets a conservative daily draft cap rather than an unlimited one.
DEFAULT_SUBREDDIT_DAILY_CAP = 3


def _compile_guarded(raw_pattern: str) -> "regex.Pattern | None":
    if len(raw_pattern) > _MAX_REGEX_PATTERN_LENGTH:
        logger.warning(
            "Regex prefilter pattern too long (%d chars, max %d); skipped",
            len(raw_pattern), _MAX_REGEX_PATTERN_LENGTH,
        )
        return None
    try:
        return regex.compile(raw_pattern, regex.IGNORECASE)
    except regex.error:
        logger.warning("Invalid regex prefilter keyword %r skipped", raw_pattern)
        return None


def _regex_search_with_timeout(
    pattern: "regex.Pattern", text: str, timeout: float = _REGEX_TIMEOUT_SECONDS
) -> bool:
    """Run ``pattern.search(text)`` with a hard, preemptible wall-clock timeout.

    A worst-case catastrophically-backtracking pattern can run for a very
    long time (effectively forever) in a naive backtracking regex engine.
    This used to be guarded by running the match in a *separate process*
    (``multiprocessing``/``fork``) with a wall-clock deadline on
    ``Queue.get`` -- but Celery's prefork worker pool runs task code inside
    *billiard* child processes that are themselves started with
    ``daemon=True``, and daemonic processes are forbidden from starting
    children of their own: ``Process.start()`` raised ``AssertionError``
    immediately, outside any ``try`` this module could put around the
    match itself, which killed the whole graph run for any campaign with a
    `regex:` keyword configured. It also forked one OS process per
    post x pattern and blocked the caller on a blocking ``Queue.get`` --
    disqualifying on constrained hardware.

    The third-party ``regex`` library (unlike stdlib ``re``) supports a true
    preemptive ``timeout=`` kwarg: its C matcher checks a wall-clock deadline
    from *inside* the match loop and raises ``TimeoutError`` partway through
    a runaway match, in the same process and thread that called it. No
    forking, no subprocess, no queue -- so it can be safely called from
    inside a daemonic billiard child (see
    ``tests/pipeline/test_prefilter.py::test_regex_prefilter_guard_runs_inside_a_daemonic_billiard_child_without_crashing``).

    This function itself is synchronous/blocking for up to ``timeout``
    seconds; callers on an asyncio event loop (``backend.pipeline.nodes.
    prefilter_node``) must invoke it via ``loop.run_in_executor`` --
    see ``matches_keyword_filters_async`` below.
    """
    try:
        return pattern.search(text, timeout=timeout) is not None
    except TimeoutError:
        logger.warning("Regex prefilter timed out (pattern=%r); treating as no match", pattern.pattern)
        return False


def matches_keyword_filters(content: str, keywords: list[str] | None) -> tuple[bool, list[str]]:
    """Case-insensitive substring match, or ``regex:``-prefixed regex (timeout-guarded).

    An empty/unset keyword list means "no filter configured" -- everything
    passes. Returns ``(passed, matched_keywords)``.

    Synchronous and potentially blocking for up to ``_REGEX_TIMEOUT_SECONDS``
    per `regex:` keyword -- call ``matches_keyword_filters_async`` from
    asyncio code instead of calling this directly.
    """
    if not keywords:
        return True, []

    matched: list[str] = []
    for kw in keywords:
        if not kw:
            continue
        if kw.startswith("regex:"):
            raw_pattern = kw[len("regex:"):]
            pattern = _compile_guarded(raw_pattern)
            if pattern is None:
                continue
            if _regex_search_with_timeout(pattern, content):
                matched.append(kw)
        else:
            if kw.lower() in content.lower():
                matched.append(kw)

    return bool(matched), matched


async def matches_keyword_filters_async(
    content: str, keywords: list[str] | None, *, loop: "asyncio.AbstractEventLoop | None" = None
) -> tuple[bool, list[str]]:
    """``matches_keyword_filters``, off the event loop.

    Runs the (possibly regex-timeout-guarded) check in the default
    executor so a slow keyword scan -- worst case,
    ``_REGEX_TIMEOUT_SECONDS`` seconds per `regex:` keyword configured on
    the campaign -- never blocks the pipeline's asyncio event loop while it
    runs. This is what ``backend.pipeline.nodes.prefilter_node`` calls.
    """
    loop = loop or asyncio.get_running_loop()
    return await loop.run_in_executor(None, matches_keyword_filters, content, keywords)


def campaign_daily_cap_key(campaign_id: int, day: str) -> str:
    return f"draftcap:campaign:{campaign_id}:{day}"


def subreddit_daily_cap_key(org_id: int, subreddit: str, day: str) -> str:
    return f"draftcap:subreddit:{org_id}:{subreddit}:{day}"


async def remaining_daily_capacity(redis_client, key: str, cap: int) -> int:
    """Read-only view of how many slots are left under ``key``, capped at ``cap``.

    Never claims/increments anything -- this is the *check* half of the
    daily-cap gate, used by the prefilter to stop obviously-over-cap posts
    from ever reaching scout/strategist (and burning LLM cost) without
    itself consuming a slot. ``reserve_daily_slot``/``reserve_daily_slots``
    below are the atomic *consume* half, called once a draft is actually
    about to be persisted -- see PRD V7 §5.3/§5.8: daily caps must be
    consumed by persisted drafts, not by posts merely considered.

    Degrades exactly like ``reserve_daily_slot``: a cap <= 0 or an
    unreachable Redis means "no capacity left", never "unlimited" (NFR §6).
    """
    if cap is None or cap <= 0:
        return 0
    if redis_client is None:
        logger.warning(
            "No Redis client available for daily cap %r; treating capacity as exhausted", key
        )
        return 0

    raw = await redis_client.get(key)
    used = int(raw or 0)
    return max(0, cap - used)


async def reserve_daily_slot(redis_client, key: str, cap: int) -> bool:
    """Atomically claim one slot under ``key``, capped at ``cap``.

    Returns ``True`` (and leaves the counter incremented) if a slot was
    available, ``False`` (and reverts the increment) if the cap was already
    reached. A cap <= 0 always refuses. Degrades safely: if Redis is
    unreachable the caller should treat that as "no slot" (never unlimited) --
    see NFR §6 "a lost daily-draft counter resets caps to safe defaults,
    never to unlimited".

    Called from ``persist_gate`` exactly once per draft that is actually
    about to be persisted (PRD V7 §5.3/§9: a post the scout/strategist never
    drafted for must not consume a day's cap) -- not from the prefilter,
    which only ``remaining_daily_capacity``-peeks.
    """
    if cap is None or cap <= 0:
        return False
    if redis_client is None:
        logger.warning("No Redis client available for daily cap %r; refusing conservatively", key)
        return False

    new_val = await redis_client.incr(key)
    if int(new_val) == 1:
        await redis_client.expire(key, DAILY_CAP_KEY_TTL_SECONDS)
    if int(new_val) > cap:
        await redis_client.decr(key)
        return False
    return True


async def reserve_daily_slots(redis_client, key_caps: list[tuple[str, int]]) -> bool:
    """Atomically claim one slot in *every* ``(key, cap)`` pair, all-or-nothing.

    A single persisted draft can need to debit more than one daily-cap
    counter at once (campaign-level and, for Reddit, subreddit-level). If
    any counter is already at its cap, every slot already claimed earlier
    in this call is released before returning ``False``, so e.g. a
    subreddit-cap miss never leaks a phantom campaign-cap slot.
    """
    reserved: list[str] = []
    for key, cap in key_caps:
        if await reserve_daily_slot(redis_client, key, cap):
            reserved.append(key)
        else:
            for k in reserved:
                await redis_client.decr(k)
            return False
    return True
