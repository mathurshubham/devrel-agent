"""Zero-LLM-cost prefilter helpers (PRD V7 §5.3 step 2).

Keyword/regex matching, and the Redis-backed daily draft caps (campaign-level
and, for Reddit, subreddit-level via ``SubredditSafetyProfile``). Dedup
against ``PostedHistory``/``DraftReply`` lives in ``backend.pipeline.nodes``
(it needs a DB session); everything here is pure or Redis-only so it is cheap
to unit test.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

logger = logging.getLogger(__name__)

#: Campaign-configured `regex:` prefilter keywords are user input running
#: against untrusted post content -- bound worst-case catastrophic
#: backtracking with a hard wall-clock timeout rather than trusting the
#: pattern. A dedicated thread pool keeps this safe outside the main thread
#: (Celery prefork workers, tests, etc. all work the same way).
_REGEX_TIMEOUT_SECONDS = 0.5
_regex_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="prefilter-regex")

#: How long a daily-cap counter key lives -- long enough to survive a slow
#: day boundary, short enough not to accumulate forever.
DAILY_CAP_KEY_TTL_SECONDS = 60 * 60 * 24 * 2


def _regex_search_with_timeout(pattern: "re.Pattern", text: str, timeout: float = _REGEX_TIMEOUT_SECONDS) -> bool:
    future = _regex_executor.submit(pattern.search, text)
    try:
        return future.result(timeout=timeout) is not None
    except FutureTimeoutError:
        future.cancel()
        logger.warning("Regex prefilter timed out (pattern=%r); treating as no match", pattern.pattern)
        return False


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
