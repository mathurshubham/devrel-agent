"""Per-platform normalizers to the shared post contract.

Every Apify actor emits its own shape; downstream (scout, strategist, drafting)
only ever sees the dict described by :class:`NormalizedPost`::

    {platform, post_id, author, author_name, author_headline,
     author_profile_url, title, content, url, top_comments[],
     reactions, comments, shares, engagement_score, posted_at}

Actors change their output without notice, so every normalizer is defensive and
every produced dict is validated with pydantic before it is accepted. An item
that fails validation is logged and skipped — a bad row must never take down a
whole polling cycle.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)


class NormalizedComment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    comment_id: str
    author: str = "Unknown"
    content: str = ""
    score: int = 0
    url: Optional[str] = None


class NormalizedPost(BaseModel):
    """The shared ingestion contract. Validated before a post is accepted."""

    model_config = ConfigDict(extra="ignore")

    platform: str
    post_id: str = Field(min_length=1)
    author: str = "Unknown"
    author_name: str = ""
    author_headline: str = ""
    author_profile_url: str = ""
    title: str = ""
    content: str = ""
    url: str = ""
    top_comments: list[NormalizedComment] = Field(default_factory=list)
    reactions: int = 0
    comments: int = 0
    shares: int = 0
    engagement_score: int = 0
    posted_at: Optional[str] = None


def _validate(candidate: dict, *, platform: str) -> Optional[dict]:
    """Validate one candidate post; log and drop it if it does not conform."""
    try:
        return NormalizedPost(**candidate).model_dump()
    except ValidationError as exc:
        logger.warning(
            "%s: dropping malformed item (post_id=%r): %s",
            platform,
            candidate.get("post_id"),
            exc.errors(include_url=False),
        )
        return None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _str(value: Any) -> str:
    return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------


def normalize_reddit(items: Iterable[dict], subreddit: str = "", max_comments: int = 5) -> list[dict]:
    """Regroup the actor's flat post/comment stream into posts with comments.

    The Reddit actor emits posts and comments as sibling dataset items
    distinguished by ``type``; comments point at their parent through
    ``postId``.
    """
    items = [i for i in items if isinstance(i, dict)]

    posts_raw = [i for i in items if i.get("type") == "post" and i.get("id")]
    comments_by_post: dict[str, list[dict]] = {}
    for item in items:
        if item.get("type") != "comment":
            continue
        parent = item.get("postId")
        if parent:
            comments_by_post.setdefault(str(parent), []).append(item)

    out: list[dict] = []
    for raw in posts_raw:
        post_id = str(raw.get("id"))

        top_comments = []
        for c in comments_by_post.get(post_id, [])[:max_comments]:
            cid = c.get("id")
            if not cid:
                continue
            permalink = c.get("permalink")
            top_comments.append(
                {
                    "comment_id": str(cid),
                    "author": _str(c.get("author")) or "Unknown",
                    "content": _str(c.get("body")),
                    "score": _int(c.get("score")),
                    "url": f"https://reddit.com{permalink}" if permalink else None,
                }
            )

        title = _str(raw.get("title"))
        num_comments = _int(raw.get("numberOfComments") or raw.get("numComments"))
        upvotes = _int(raw.get("upVotes") or raw.get("score") or raw.get("ups"))

        candidate = {
            "platform": "REDDIT",
            "post_id": post_id,
            "author": _str(raw.get("author")) or "Unknown",
            "author_name": _str(raw.get("author")),
            "author_headline": "",
            "author_profile_url": (
                f"https://reddit.com/user/{raw.get('author')}" if raw.get("author") else ""
            ),
            "title": title,
            "content": _str(raw.get("selfText") or raw.get("body") or title) or "[No content]",
            "url": _str(raw.get("url")) or f"https://reddit.com/r/{subreddit}",
            "top_comments": top_comments,
            "reactions": upvotes,
            "comments": num_comments or len(top_comments),
            "shares": 0,
            "engagement_score": upvotes + (num_comments or len(top_comments)),
            "posted_at": _parse_timestamp(
                raw.get("createdAt") or raw.get("created_utc") or raw.get("created")
            ),
        }
        validated = _validate(candidate, platform="REDDIT")
        if validated:
            out.append(validated)
    return out


# ---------------------------------------------------------------------------
# Twitter / X
# ---------------------------------------------------------------------------


def normalize_twitter(items: Iterable[dict]) -> list[dict]:
    """Map the kaitoeasyapi tweet shape onto the shared contract."""
    out: list[dict] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        post_id = raw.get("id") or raw.get("id_str") or raw.get("tweet_id")
        if not post_id:
            continue

        author_raw = raw.get("author") or {}
        if not isinstance(author_raw, dict):
            author_raw = {}
        username = _str(author_raw.get("userName") or author_raw.get("screen_name"))
        display_name = _str(author_raw.get("name") or author_raw.get("displayName"))
        bio = _str(
            author_raw.get("description")
            or author_raw.get("bio")
            or author_raw.get("rawDescription")
        )
        profile_url = _str(
            author_raw.get("url")
            or author_raw.get("twitterUrl")
            or (f"https://twitter.com/{username}" if username else "")
        )

        likes = _int(raw.get("likeCount") or raw.get("favoriteCount") or raw.get("favorite_count"))
        replies = _int(raw.get("replyCount") or raw.get("reply_count"))
        retweets = _int(raw.get("retweetCount") or raw.get("retweet_count"))
        quotes = _int(raw.get("quoteCount") or raw.get("quote_count"))

        candidate = {
            "platform": "TWITTER",
            "post_id": str(post_id),
            "author": username or display_name or "Unknown",
            "author_name": display_name or username,
            "author_headline": bio,
            "author_profile_url": profile_url,
            "title": "",
            "content": _str(raw.get("text") or raw.get("full_text")) or "[No content]",
            "url": _str(raw.get("url") or raw.get("twitterUrl"))
            or f"https://twitter.com/i/web/status/{post_id}",
            "top_comments": [],
            "reactions": likes,
            "comments": replies,
            "shares": retweets + quotes,
            "engagement_score": likes + replies + retweets + quotes,
            "posted_at": _parse_timestamp(raw.get("createdAt") or raw.get("created_at")),
        }
        validated = _validate(candidate, platform="TWITTER")
        if validated:
            out.append(validated)
    return out


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------


def _is_job_post(raw: dict) -> bool:
    """Recruiting posts are noise for DevRel engagement — drop them."""
    content = raw.get("content")
    if isinstance(content, dict) and content.get("type") == "job":
        return True
    return raw.get("type") == "job"


def _has_linkedin_id(raw: dict) -> bool:
    return bool(
        raw.get("id")
        or raw.get("urn")
        or raw.get("activityUrn")
        or raw.get("activity_id")  # apimaestro
        or raw.get("full_urn")  # apimaestro
    )


def normalize_linkedin(items: Iterable[dict]) -> list[dict]:
    """Normalize LinkedIn posts across the three actors we support.

    Field names vary widely between actors, so every lookup walks a fallback
    chain. Job posts and items with no resolvable id are dropped.
    """
    out: list[dict] = []
    skipped_jobs = 0

    for raw in items:
        if not isinstance(raw, dict):
            continue
        if _is_job_post(raw):
            skipped_jobs += 1
            continue
        if not _has_linkedin_id(raw):
            continue

        # URN resolution: prefer explicit URN fields, fall back to a bare id.
        urn = (
            raw.get("full_urn")
            or raw.get("urn")
            or raw.get("activityUrn")
            or raw.get("activity_id")
            or raw.get("id", "")
        )
        if urn and not str(urn).startswith("urn:li:"):
            urn = f"urn:li:activity:{urn}"

        author_raw = raw.get("author") or raw.get("actor") or {}
        if isinstance(author_raw, dict):
            author = _str(
                author_raw.get("name")
                or author_raw.get("fullName")
                or author_raw.get("localizedName")
            )
            headline = _str(
                author_raw.get("headline")
                or author_raw.get("subtitle")
                or author_raw.get("subDescription")
                or author_raw.get("title")
                or author_raw.get("description")
                or author_raw.get("occupation")
            )
            profile_url = _str(
                author_raw.get("profileUrl")
                or author_raw.get("profile_url")
                or author_raw.get("url")
                or author_raw.get("publicProfileUrl")
                or author_raw.get("publicId")
            )
            if profile_url and not profile_url.startswith("http"):
                profile_url = f"https://www.linkedin.com/in/{profile_url}"
        else:
            author = _str(author_raw)
            headline = ""
            profile_url = ""

        content = _str(raw.get("text") or raw.get("commentary") or raw.get("title"))
        if not content:
            nested = raw.get("content")
            if isinstance(nested, dict):
                content = _str(nested.get("text"))
            elif isinstance(nested, str):
                content = nested

        url = _str(
            raw.get("post_url") or raw.get("url") or raw.get("postUrl")
        ) or f"https://www.linkedin.com/feed/update/{urn}/"

        # Engagement: both the flat shape and the apimaestro stats-nested shape.
        stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else {}
        reactions = _int(
            stats.get("total_reactions")
            or raw.get("numLikes")
            or raw.get("likeCount")
            or raw.get("totalReactionCount")
            or raw.get("num_reactions")
        )
        comments = _int(
            stats.get("comments")
            or raw.get("numComments")
            or raw.get("commentCount")
            or raw.get("commentsCount")
            or raw.get("comments_count")
        )
        shares = _int(
            stats.get("shares")
            or raw.get("numShares")
            or raw.get("shareCount")
            or raw.get("repostsCount")
            or raw.get("shares_count")
        )

        candidate = {
            "platform": "LINKEDIN",
            "post_id": str(urn),
            "author": author or "Unknown",
            "author_name": author,
            "author_headline": headline,
            "author_profile_url": profile_url,
            "title": "",
            "content": content,
            "url": url,
            "top_comments": [],
            "reactions": reactions,
            "comments": comments,
            "shares": shares,
            "engagement_score": reactions + comments + shares,
            "posted_at": parse_linkedin_posted_at(raw),
        }
        validated = _validate(candidate, platform="LINKEDIN")
        if validated:
            out.append(validated)

    if skipped_jobs:
        logger.info("LinkedIn: skipped %d job post(s)", skipped_jobs)
    return out


def parse_linkedin_posted_at(raw: dict) -> Optional[str]:
    """Publish time as an ISO-8601 UTC string, or ``None``.

    Reads the apimaestro ``posted_at`` object defensively and falls back to a
    few flat keys other actors use. A relative-only value ("21m", "1w") cannot
    be resolved to an absolute instant, so it yields ``None`` rather than a
    guess — downstream the stale filter keeps such posts.
    """
    pa = raw.get("posted_at")
    if isinstance(pa, dict):
        return _from_datetime_string(pa.get("date")) or _from_epoch_ms(pa.get("timestamp"))
    if isinstance(pa, (int, float)) and not isinstance(pa, bool):
        return _from_epoch_ms(pa)
    if isinstance(pa, str):
        return _from_datetime_string(pa)

    for key in ("postedAt", "posted_at_timestamp", "postedDate", "time", "createdAt"):
        value = raw.get(key)
        parsed = (
            _from_epoch_ms(value)
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else _from_datetime_string(value)
        )
        if parsed:
            return parsed
    return None


def _from_epoch_ms(value: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _from_datetime_string(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_timestamp(value: Any) -> Optional[str]:
    """Best-effort timestamp parse for Reddit/Twitter fields.

    Accepts ISO strings, Twitter's ``"Wed Oct 10 20:19:24 +0000 2018"``, epoch
    seconds and epoch milliseconds.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # Epoch seconds vs milliseconds: anything past ~year 2286 in seconds is ms.
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str):
        iso = _from_datetime_string(value)
        if iso:
            return iso
        try:
            return (
                datetime.strptime(value.strip(), "%a %b %d %H:%M:%S %z %Y")
                .astimezone(timezone.utc)
                .isoformat()
            )
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Stale filter (LinkedIn)
# ---------------------------------------------------------------------------


def filter_stale_posts(
    posts: list[dict],
    stale_days: Optional[int],
    stale_min_engagement: Optional[int],
) -> tuple[list[dict], int]:
    """Recency-aware filter: drop a post only when it is BOTH old AND quiet.

    A post is dropped when its age exceeds ``stale_days`` *and* its
    ``engagement_score`` is below ``stale_min_engagement``. Recent posts are
    always kept regardless of engagement, and a post whose ``posted_at`` is
    missing or unparseable is kept (we cannot judge its age). Returns
    ``(kept, dropped_count)``; a no-op when either threshold is unset.
    """
    if not stale_days or stale_min_engagement is None:
        return posts, 0

    now = datetime.now(timezone.utc)
    kept: list[dict] = []
    dropped = 0

    for post in posts:
        posted = post.get("posted_at")
        age_days = None
        if posted:
            try:
                dt = datetime.fromisoformat(posted)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_days = (now - dt).total_seconds() / 86400
            except (TypeError, ValueError):
                age_days = None

        if (
            age_days is not None
            and age_days > stale_days
            and _int(post.get("engagement_score")) < stale_min_engagement
        ):
            dropped += 1
            continue
        kept.append(post)

    if dropped:
        logger.info(
            "Discarded %d stale low-engagement post(s) (older than %sd with engagement < %s)",
            dropped,
            stale_days,
            stale_min_engagement,
        )
    return kept, dropped


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


def normalize_items(platform: str, items: Iterable[dict], **kwargs: Any) -> list[dict]:
    """Normalize raw dataset items for ``platform``."""
    normalized_platform = (platform or "").upper()
    if normalized_platform == "REDDIT":
        return normalize_reddit(items, **kwargs)
    if normalized_platform == "TWITTER":
        return normalize_twitter(items)
    if normalized_platform == "LINKEDIN":
        return normalize_linkedin(items)
    raise ValueError(f"Unsupported platform for normalization: {platform!r}")
