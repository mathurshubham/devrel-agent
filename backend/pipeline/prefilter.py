"""Zero-LLM-cost prefilter helpers (PRD V7 §5.3 step 2).

Keyword/regex matching, and the Redis-backed daily draft caps (campaign-level
and, for Reddit, subreddit-level via ``SubredditSafetyProfile``). Dedup
against ``PostedHistory``/``DraftReply`` lives in ``backend.pipeline.nodes``
(it needs a DB session); everything here is pure or Redis-only so it is cheap
to unit test.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import re

logger = logging.getLogger(__name__)

#: Campaign-configured `regex:` prefilter keywords are user input running
#: against untrusted post content -- bound worst-case catastrophic
#: backtracking with a hard wall-clock timeout rather than trusting the
#: pattern.
_REGEX_TIMEOUT_SECONDS = 0.5

try:
    _mp_ctx = mp.get_context("fork")
except ValueError:  # pragma: no cover - non-POSIX platform
    _mp_ctx = mp.get_context()

#: How long a daily-cap counter key lives -- long enough to survive a slow
#: day boundary, short enough not to accumulate forever.
DAILY_CAP_KEY_TTL_SECONDS = 60 * 60 * 24 * 2


def _regex_worker(pattern_str: str, flags: int, text: str, out_queue) -> None:
    try:
        out_queue.put(re.search(pattern_str, text, flags) is not None)
    except Exception:  # noqa: BLE001 - never let the worker die silently
        out_queue.put(False)


def _regex_search_with_timeout(pattern: "re.Pattern", text: str, timeout: float = _REGEX_TIMEOUT_SECONDS) -> bool:
    """Run ``pattern.search(text)`` with a hard wall-clock timeout.

    A worst-case catastrophically-backtracking pattern can run for a very
    long time (effectively forever) in Python's ``re`` engine, with no way
    to cancel it once started. This runs the match in a *separate process*
    rather than a thread: CPython's ``re`` engine never releases the GIL
    mid-match, so a thread-based timeout cannot actually preempt a runaway
    match -- the "timed-out" waiter would itself block forever trying to
    re-acquire a GIL the runaway thread never gives up. A child process has
    its own GIL and can be killed outright when it overruns.
    """
    out_queue: "mp.Queue" = _mp_ctx.Queue(maxsize=1)
    proc = _mp_ctx.Process(
        target=_regex_worker,
        args=(pattern.pattern, pattern.flags, text, out_queue),
        daemon=True,
    )
    proc.start()
    try:
        return out_queue.get(timeout=timeout)
    except queue.Empty:
        logger.warning("Regex prefilter timed out (pattern=%r); treating as no match", pattern.pattern)
        return False
    finally:
        if proc.is_alive():
            proc.terminate()
        proc.join(timeout=1.0)


def matches_keyword_filters(content: str, keywords: list[str] | None) -> tuple[bool, list[str]]:
    """Case-insensitive substring match, or ``regex:``-prefixed regex (timeout-guarded).

    An empty/unset keyword list means "no filter configured" -- everything
    passes. Returns ``(passed, matched_keywords)``.
    """
    if not keywords:
        return True, []

    matched: list[str] = []
    for kw in keywords:
        if not kw:
            continue
        if kw.startswith("regex:"):
            raw_pattern = kw[len("regex:"):]
            try:
                pattern = re.compile(raw_pattern, re.IGNORECASE)
            except re.error:
                logger.warning("Invalid regex prefilter keyword %r skipped", kw)
                continue
            if _regex_search_with_timeout(pattern, content):
                matched.append(kw)
        else:
            if kw.lower() in content.lower():
                matched.append(kw)

    return bool(matched), matched


def campaign_daily_cap_key(campaign_id: int, day: str) -> str:
    return f"draftcap:campaign:{campaign_id}:{day}"


def subreddit_daily_cap_key(org_id: int, subreddit: str, day: str) -> str:
    return f"draftcap:subreddit:{org_id}:{subreddit}:{day}"


async def reserve_daily_slot(redis_client, key: str, cap: int) -> bool:
    """Atomically claim one slot under ``key``, capped at ``cap``.

    Returns ``True`` (and leaves the counter incremented) if a slot was
    available, ``False`` (and reverts the increment) if the cap was already
    reached. A cap <= 0 always refuses. Degrades safely: if Redis is
    unreachable the caller should treat that as "no slot" (never unlimited) --
    see NFR §6 "a lost daily-draft counter resets caps to safe defaults,
    never to unlimited".
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
