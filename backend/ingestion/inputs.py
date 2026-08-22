"""Per-platform Apify actor input builders and the actor registry.

Ported from ``social-agent``'s ``build_actor_input`` / ``build_twitter_input``
and adapted to the V7 campaign shape: a campaign carries a single ``value``
(subreddit name, LinkedIn keyword/profile/company URL, or Twitter query) plus a
free-form ``platform_config`` JSONB dict holding the per-platform knobs that
used to be individual columns on ``Target``.

Nothing here does I/O, so these functions are pure and cheap to unit test.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ActorKey(str, Enum):
    """Registry keys — also the keys used in ``OrgSettings.actor_overrides``."""

    REDDIT = "reddit"
    TWITTER = "twitter"
    LINKEDIN_KEYWORD = "linkedin_keyword"
    LINKEDIN_PROFILE = "linkedin_profile"
    LINKEDIN_COMPANY = "linkedin_company"


#: Default actor per registry key. Overridable per org via
#: ``OrgSettings.actor_overrides`` = ``{registry_key: actor_id}``.
DEFAULT_ACTORS: dict[str, str] = {
    ActorKey.REDDIT.value: "automation-lab/reddit-scraper",
    ActorKey.TWITTER.value: "kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest",
    ActorKey.LINKEDIN_KEYWORD.value: "apimaestro/linkedin-posts-search-scraper-no-cookies",
    ActorKey.LINKEDIN_PROFILE.value: "apimaestro/linkedin-profile-posts",
    ActorKey.LINKEDIN_COMPANY.value: "scraper-engine/linkedin-company-post-scraper",
}


def resolve_actor(key: str | ActorKey, org_settings: Any = None) -> str:
    """Actor id for a registry key, honouring the org's overrides."""
    key_str = key.value if isinstance(key, ActorKey) else str(key)
    overrides = getattr(org_settings, "actor_overrides", None) or {}
    if isinstance(overrides, dict):
        override = overrides.get(key_str)
        if isinstance(override, str) and override.strip():
            return override.strip()
    try:
        return DEFAULT_ACTORS[key_str]
    except KeyError:
        raise ValueError(f"Unknown actor registry key: {key_str!r}") from None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _config(campaign: Any) -> dict:
    cfg = getattr(campaign, "platform_config", None)
    return cfg if isinstance(cfg, dict) else {}


def _platform_name(campaign: Any) -> str:
    platform = getattr(campaign, "platform", "")
    return (getattr(platform, "value", platform) or "").upper()


def _int_or_none(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------


def build_reddit_input(campaign: Any) -> dict:
    """Input for the Reddit scraper actor.

    ``campaign.value`` is a subreddit name; ``r/`` prefixes and stray slashes
    are tolerated so operators can paste either form.
    """
    cfg = _config(campaign)
    subreddit = str(getattr(campaign, "value", "") or "").strip()
    subreddit = subreddit.removeprefix("r/").removeprefix("/r/").strip("/")

    return {
        "urls": [f"https://www.reddit.com/r/{subreddit}/"],
        "sort": cfg.get("sort") or "top",
        "timeFilter": cfg.get("time_filter") or cfg.get("timeFilter") or "day",
        "maxPostsPerSource": _int_or_none(cfg.get("max_posts_per_source")) or 15,
        "includeComments": True,
        "maxCommentsPerPost": _int_or_none(cfg.get("max_comments_per_post")) or 5,
    }


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------


def detect_linkedin_mode(value: str) -> str:
    """``profile`` | ``company`` | ``keyword``, inferred from the campaign value."""
    lowered = (value or "").lower()
    if "linkedin.com/in/" in lowered:
        return "profile"
    if "linkedin.com/company/" in lowered:
        return "company"
    return "keyword"


def build_linkedin_input(campaign: Any) -> tuple[str, dict]:
    """Return ``(actor_registry_key, actor_input)`` for a LinkedIn campaign."""
    cfg = _config(campaign)
    value = str(getattr(campaign, "value", "") or "").strip()
    mode = cfg.get("mode") or detect_linkedin_mode(value)

    if mode == "profile":
        return ActorKey.LINKEDIN_PROFILE.value, {
            "profileUrl": value,
            "limit": _int_or_none(cfg.get("limit")) or 10,
        }

    if mode == "company":
        return ActorKey.LINKEDIN_COMPANY.value, {
            "companyUrl": value,
            "limit": _int_or_none(cfg.get("limit")) or 10,
        }

    # keyword search
    keyword = f'"{value}"' if cfg.get("exact_match") else value
    raw_sort = cfg.get("sort_type") or "date_posted"
    # The actor renamed "date" to "date_posted"; accept the legacy value.
    sort_type = "date_posted" if raw_sort == "date" else raw_sort

    actor_input: dict = {
        "keyword": keyword,
        "limit": _int_or_none(cfg.get("limit")) or 30,
        "sort_type": sort_type,
        "page_number": 1,
    }
    for key in (
        "date_filter",
        "company_urns",
        "author_company_urns",
        "author_industry_urns",
        "author_job_title",
        "member_urns",
    ):
        if cfg.get(key):
            actor_input[key] = cfg[key]
    return ActorKey.LINKEDIN_KEYWORD.value, actor_input


# ---------------------------------------------------------------------------
# Twitter / X
# ---------------------------------------------------------------------------

#: The kaitoeasyapi actor rejects runs asking for fewer than 20 items.
TWITTER_MIN_ITEMS = 20


def build_twitter_input(campaign: Any) -> dict:
    """Input for the kaitoeasyapi Twitter/X actor."""
    cfg = _config(campaign)
    value = str(getattr(campaign, "value", "") or "").strip()
    limit = _int_or_none(cfg.get("limit")) or TWITTER_MIN_ITEMS

    actor_input: dict = {
        "searchTerms": [value],
        "maxItems": max(limit, TWITTER_MIN_ITEMS),
        "queryType": cfg.get("query_type") or "Latest",
    }
    if cfg.get("lang"):
        actor_input["lang"] = cfg["lang"]

    since_days = _int_or_none(cfg.get("since_days"))
    if since_days:
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        actor_input["since_time"] = str(int(since.timestamp()))

    for cfg_key, actor_field in (
        ("min_retweets", "min_retweets"),
        ("min_faves", "min_faves"),
        ("min_replies", "min_replies"),
    ):
        parsed = _int_or_none(cfg.get(cfg_key))
        if parsed:
            actor_input[actor_field] = parsed

    for cfg_key, actor_field in (
        ("filter_blue_verified", "filter:blue_verified"),
        ("filter_has_engagement", "filter:has_engagement"),
        ("filter_media", "filter:media"),
    ):
        if cfg.get(cfg_key):
            actor_input[actor_field] = True

    return actor_input


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


def build_actor_input(campaign: Any, org_settings: Any = None) -> tuple[str, dict]:
    """Return ``(actor_id, actor_input)`` for any campaign.

    The actor id is already resolved through the org's ``actor_overrides``.
    """
    platform = _platform_name(campaign)

    if platform == "REDDIT":
        key, actor_input = ActorKey.REDDIT.value, build_reddit_input(campaign)
    elif platform == "TWITTER":
        key, actor_input = ActorKey.TWITTER.value, build_twitter_input(campaign)
    elif platform == "LINKEDIN":
        key, actor_input = build_linkedin_input(campaign)
    else:
        raise ValueError(f"Unsupported campaign platform: {platform!r}")

    return resolve_actor(key, org_settings), actor_input
