"""Analyst ingest sourcing (PRD V7 §5.6): keyword campaigns + tracked authors
+ competitors.

Every source is routed through ``backend.ingestion.service.ingest_campaign``
-- the same Apify spend counter, token vault, and normalization the reply
pipeline's ``ingest_node`` uses -- so Analyst ingestion is budget-gated
exactly like graph #1's, against the same org monthly Apify budget.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select

from backend.ingestion.inputs import detect_linkedin_mode
from backend.ingestion.service import BudgetExceededError, ingest_campaign
from backend.ingestion.tokens import NoUsableTokenError
from backend.models import Campaign, CampaignStatus, Competitor, PlatformEnum, TargetAuthor

logger = logging.getLogger(__name__)


@dataclass
class _PseudoCampaign:
    """Just enough of ``Campaign``'s shape for ``build_actor_input``/
    ``ingest_campaign``. TargetAuthor/Competitor rows have no Campaign row of
    their own -- the Analyst pipeline scrapes their profile/company URL
    directly rather than running a keyword search."""

    org_id: int
    platform: PlatformEnum
    value: str
    platform_config: dict = field(default_factory=dict)
    #: Only used for cost *estimates* elsewhere; ingest_campaign itself never
    #: reads this. Weekly cadence is the honest default for these sources.
    poll_frequency_minutes: int = 10080
    daily_draft_cap: int = 0


async def _sources_for_org(
    db, org_id: int
) -> tuple[list[Campaign], list[TargetAuthor], list[Competitor]]:
    campaigns = list(
        (
            await db.execute(
                select(Campaign).where(
                    Campaign.org_id == org_id, Campaign.status == CampaignStatus.ACTIVE
                )
            )
        )
        .scalars()
        .all()
    )
    authors = list(
        (await db.execute(select(TargetAuthor).where(TargetAuthor.org_id == org_id)))
        .scalars()
        .all()
    )
    competitors = list(
        (await db.execute(select(Competitor).where(Competitor.org_id == org_id)))
        .scalars()
        .all()
    )
    return campaigns, authors, competitors


def _author_pseudo_campaign(org_id: int, author: TargetAuthor) -> Optional[_PseudoCampaign]:
    if not author.profile_url:
        return None
    return _PseudoCampaign(
        org_id=org_id,
        platform=PlatformEnum.LINKEDIN,
        value=author.profile_url,
        platform_config={"mode": "profile", "limit": 10},
    )


def _competitor_pseudo_campaign(org_id: int, competitor: Competitor) -> Optional[_PseudoCampaign]:
    if not competitor.url:
        return None
    platform = competitor.platform or PlatformEnum.LINKEDIN
    cfg: dict = {}
    if platform == PlatformEnum.LINKEDIN:
        cfg["mode"] = detect_linkedin_mode(competitor.url)
    return _PseudoCampaign(org_id=org_id, platform=platform, value=competitor.url, platform_config=cfg)


async def _run_source(db, org_id, pseudo_campaign, org_settings, vault_tokens, redis_client, errors: list[str]) -> list[dict]:
    """One ingest source, degrading to "no posts" on any failure.

    A single exhausted-budget or unreachable-source failure must not sink
    the whole Analyst run -- every other source still gets a chance, and the
    run still produces whatever brief it can from what it collected (PRD V7
    §5.6: "Each node degrades gracefully to defaults rather than dropping
    the post").
    """
    try:
        return await ingest_campaign(
            db, pseudo_campaign, org_settings, vault_tokens, redis_client=redis_client
        )
    except (BudgetExceededError, NoUsableTokenError) as exc:
        errors.append(str(exc))
        logger.warning("Analyst ingest source skipped for org %s: %s", org_id, exc)
        return []
    except Exception as exc:  # noqa: BLE001 - one bad source must not sink the whole run
        errors.append(f"ingest error: {exc}")
        logger.exception("Analyst ingest source failed for org %s", org_id)
        return []


async def gather_analyst_posts(
    db,
    org_id: int,
    org_settings,
    vault_tokens,
    *,
    redis_client=None,
) -> tuple[list[dict], list[dict], list[str]]:
    """Ingest keyword campaigns + tracked authors + competitors for one org.

    Returns ``(posts, competitor_posts, source_errors)``. ``posts`` are
    deduplicated by ``post_id`` (a tracked author's own posts can otherwise
    surface twice -- once via a keyword campaign, once via their profile
    scrape). ``competitor_posts`` carry a ``competitor`` key and are never
    fed through per-post classification -- they go straight into the brief's
    "Competitive Watch" section (ported from ``social-agent``'s
    ``AnalystService.generate_intel_brief``).
    """
    campaigns, authors, competitors = await _sources_for_org(db, org_id)

    errors: list[str] = []
    seen_post_ids: set[str] = set()
    posts: list[dict] = []

    for campaign in campaigns:
        for post in await _run_source(db, org_id, campaign, org_settings, vault_tokens, redis_client, errors):
            pid = post.get("post_id")
            if pid in seen_post_ids:
                continue
            seen_post_ids.add(pid)
            posts.append(post)

    for author in authors:
        pseudo = _author_pseudo_campaign(org_id, author)
        if pseudo is None:
            continue
        for post in await _run_source(db, org_id, pseudo, org_settings, vault_tokens, redis_client, errors):
            pid = post.get("post_id")
            if pid in seen_post_ids:
                continue
            seen_post_ids.add(pid)
            posts.append(post)

    competitor_posts: list[dict] = []
    for competitor in competitors:
        pseudo = _competitor_pseudo_campaign(org_id, competitor)
        if pseudo is None:
            continue
        fetched = await _run_source(db, org_id, pseudo, org_settings, vault_tokens, redis_client, errors)
        competitor_posts.extend({**post, "competitor": competitor.name} for post in fetched)

    return posts, competitor_posts, errors
