"""Engagement outcomes poller (PRD V7 §5.7).

For ``POSTED`` drafts with a ``live_url``, re-scrapes metrics at +24h and
+72h and persists ``EngagementOutcome`` rows. Reddit only for M2, via the
free ``<permalink>.json`` endpoint (``httpx``, no auth, no Apify spend).
LinkedIn/Twitter need an Apify metric re-scrape per the PRD and are
explicitly out of scope here -- logged and skipped, not silently ignored.

``DraftReply`` has no dedicated "when did the org's reply go live" column;
``confirm_posted_draft`` (backend/api/inbox.py) already (over)loads
``posted_at_source`` with that timestamp at confirm-time, so this poller
reads it the same way rather than adding a new column.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from backend.models import DraftReply, DraftStatus, EngagementOutcome, PlatformEnum

logger = logging.getLogger(__name__)

#: When outcomes are due, relative to the reply going live.
OUTCOME_HOURS = (24, 72)

_REDDIT_UA = "Sentinel/1.0 (engagement outcomes poller; https://github.com/mathurshubham/devrel-agent)"


async def fetch_reddit_comment_metrics(http_client: httpx.AsyncClient, live_url: str) -> Optional[dict]:
    """Best-effort reactions/replies for a Reddit comment permalink.

    Reddit's ``.json`` endpoint on a comment permalink isolates that comment
    as the sole child of the comments listing (plus its own replies) -- no
    auth needed. Returns ``None`` on any fetch/parse failure (never raises;
    a bad row must not take down the whole poll tick, same convention as
    the ingestion normalizers).
    """
    url = live_url.rstrip("/") + ".json"
    try:
        resp = await http_client.get(url, headers={"User-Agent": _REDDIT_UA})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Reddit outcomes fetch failed for %s: %s", live_url, exc)
        return None

    if not isinstance(data, list) or len(data) < 2:
        return None
    children = (data[1].get("data") or {}).get("children") or []
    if not children:
        return None
    comment = children[0].get("data") or {}
    if not isinstance(comment, dict):
        return None

    reply_count = 0
    replies_node = comment.get("replies")
    if isinstance(replies_node, dict):
        reply_count = len((replies_node.get("data") or {}).get("children") or [])

    try:
        reactions = int(comment.get("score") or 0)
    except (TypeError, ValueError):
        reactions = 0

    return {"reactions": reactions, "replies": reply_count, "reposts": 0}


async def _due_hours(db, draft_id: int, posted_at: datetime, now: datetime) -> list[int]:
    existing = set(
        (
            await db.execute(
                select(EngagementOutcome.hours_after).where(EngagementOutcome.draft_id == draft_id)
            )
        )
        .scalars()
        .all()
    )
    return [h for h in OUTCOME_HOURS if h not in existing and now >= posted_at + timedelta(hours=h)]


async def poll_engagement_outcomes(session_local, http_client: Optional[httpx.AsyncClient] = None) -> dict:
    """Poll every POSTED draft with a live_url for due +24h/+72h outcomes."""
    own_client = http_client is None
    http_client = http_client or httpx.AsyncClient(timeout=15.0)
    now = datetime.now(timezone.utc)
    stats = {"checked": 0, "recorded": 0, "skipped_platform": 0, "errors": 0}

    try:
        async with session_local() as db:
            drafts = (
                await db.execute(
                    select(DraftReply).where(
                        DraftReply.status == DraftStatus.POSTED,
                        DraftReply.live_url.is_not(None),
                    )
                )
            ).scalars().all()

            for draft in drafts:
                posted_at = draft.posted_at_source
                if posted_at is None:
                    continue
                if posted_at.tzinfo is None:
                    posted_at = posted_at.replace(tzinfo=timezone.utc)

                due = await _due_hours(db, draft.id, posted_at, now)
                if not due:
                    continue

                if draft.platform != PlatformEnum.REDDIT:
                    logger.info(
                        "TODO(M3): outcomes polling for %s is not implemented yet "
                        "(needs an Apify metric re-scrape per PRD V7 §5.7) -- draft %s",
                        draft.platform, draft.id,
                    )
                    stats["skipped_platform"] += 1
                    continue

                stats["checked"] += 1
                metrics = await fetch_reddit_comment_metrics(http_client, draft.live_url)
                if metrics is None:
                    stats["errors"] += 1
                    continue

                got_response = metrics["replies"] > 0 or metrics["reactions"] > 0
                for hours in due:
                    db.add(
                        EngagementOutcome(
                            draft_id=draft.id,
                            hours_after=hours,
                            reactions=metrics["reactions"],
                            replies=metrics["replies"],
                            reposts=metrics["reposts"],
                            got_response=got_response,
                        )
                    )
                    stats["recorded"] += 1

            await db.commit()
    finally:
        if own_client:
            await http_client.aclose()

    return stats
