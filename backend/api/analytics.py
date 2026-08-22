"""Analytics API (PRD V7 §5.7): angle leaderboard, platform performance,
draft totals + reject-reason breakdown, and spend meters (LLM + Apify).
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.ingestion.service import get_month_spend_usd, monthly_budget_usd
from backend.models import DraftReply, DraftStatus, EngagementOutcome, OrgLLMConfig
from backend.pipeline.templates import top_angles
from backend.utils.auth import get_current_session
from backend.utils.cost_guard import _daily_tokens_key, _monthly_cost_key
from backend.utils.org_lookups import get_org_settings
from backend.utils.redis_dep import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


def _engagement_total(outcome: EngagementOutcome) -> int:
    return (outcome.reactions or 0) + (outcome.replies or 0) + (outcome.reposts or 0)


async def _best_outcome_by_draft(db: AsyncSession, draft_ids: list[int]) -> dict[int, EngagementOutcome]:
    """One outcome per draft -- the highest ``hours_after`` capture (a later
    re-scrape supersedes an earlier one for "how did this land" purposes)."""
    if not draft_ids:
        return {}
    outcomes = (
        await db.execute(select(EngagementOutcome).where(EngagementOutcome.draft_id.in_(draft_ids)))
    ).scalars().all()
    best: dict[int, EngagementOutcome] = {}
    for o in outcomes:
        existing = best.get(o.draft_id)
        if existing is None or (o.hours_after or 0) > (existing.hours_after or 0):
            best[o.draft_id] = o
    return best


@router.get("/summary")
async def get_analytics_summary(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
    redis_client=Depends(get_redis),
):
    """Angle leaderboard (per platform), platform performance, draft totals
    + reject-reason breakdown, and LLM/Apify spend meters."""
    org_id = session["org_id"]

    drafts = (await db.execute(select(DraftReply).where(DraftReply.org_id == org_id))).scalars().all()
    best_outcome = await _best_outcome_by_draft(db, [d.id for d in drafts])

    total_drafted = len(drafts)
    total_posted = sum(1 for d in drafts if d.status == DraftStatus.POSTED)
    total_rejected = sum(1 for d in drafts if d.status == DraftStatus.REJECTED)
    reject_reasons = Counter(
        (d.reject_reason or "unspecified") for d in drafts if d.status == DraftStatus.REJECTED
    )

    angle_stats: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"drafted": 0, "posted": 0, "engagement_sum": 0, "engagement_n": 0}
    )
    platform_stats: dict[str, dict] = defaultdict(
        lambda: {"drafted": 0, "posted": 0, "rejected": 0, "engagement_sum": 0, "engagement_n": 0}
    )

    for d in drafts:
        platform = d.platform.value if d.platform else "UNKNOWN"
        angle = d.angle_name or "Unknown"
        angle_bucket = angle_stats[(platform, angle)]
        platform_bucket = platform_stats[platform]

        angle_bucket["drafted"] += 1
        platform_bucket["drafted"] += 1

        if d.status == DraftStatus.POSTED:
            angle_bucket["posted"] += 1
            platform_bucket["posted"] += 1
            outcome = best_outcome.get(d.id)
            if outcome:
                engagement = _engagement_total(outcome)
                angle_bucket["engagement_sum"] += engagement
                angle_bucket["engagement_n"] += 1
                platform_bucket["engagement_sum"] += engagement
                platform_bucket["engagement_n"] += 1
        elif d.status == DraftStatus.REJECTED:
            platform_bucket["rejected"] += 1

    def _rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 2) if denominator else 0.0

    def _avg(total: int, n: int) -> float:
        return round(total / n, 1) if n else 0.0

    angle_leaderboard = sorted(
        (
            {
                "platform": platform,
                "angle": angle,
                "drafted": s["drafted"],
                "posted": s["posted"],
                "acceptance_rate": _rate(s["posted"], s["drafted"]),
                "avg_engagement": _avg(s["engagement_sum"], s["engagement_n"]),
            }
            for (platform, angle), s in angle_stats.items()
        ),
        key=lambda row: (row["avg_engagement"], row["acceptance_rate"]),
        reverse=True,
    )

    platform_performance = [
        {
            "platform": platform,
            "drafted": s["drafted"],
            "posted": s["posted"],
            "rejected": s["rejected"],
            "acceptance_rate": _rate(s["posted"], s["drafted"]),
            "avg_engagement": _avg(s["engagement_sum"], s["engagement_n"]),
        }
        for platform, s in platform_stats.items()
    ]

    # ── Spend meters ──────────────────────────────────────────────────────
    llm_config = await db.execute(select(OrgLLMConfig).where(OrgLLMConfig.org_id == org_id))
    llm_config = llm_config.scalar_one_or_none()

    daily_tokens_raw = await redis_client.get(_daily_tokens_key(org_id))
    monthly_cost_raw = await redis_client.get(_monthly_cost_key(org_id))

    org_settings = await get_org_settings(db, org_id)
    apify_spent = await get_month_spend_usd(org_id, redis_client)
    apify_budget = monthly_budget_usd(org_settings)

    return {
        "totals": {
            "drafted": total_drafted,
            "posted": total_posted,
            "rejected": total_rejected,
            "reject_reasons": dict(reject_reasons),
        },
        "angle_leaderboard": angle_leaderboard,
        "platform_performance": platform_performance,
        "spend": {
            "llm": {
                "daily_tokens": int(daily_tokens_raw or 0),
                "monthly_cost_usd": float(monthly_cost_raw or 0.0),
                "max_daily_tokens": llm_config.max_daily_llm_tokens if llm_config else None,
                "max_monthly_cost_usd": float(llm_config.max_monthly_llm_cost_usd)
                if llm_config and llm_config.max_monthly_llm_cost_usd is not None
                else None,
            },
            "apify": {
                "month": datetime.now(timezone.utc).strftime("%Y-%m"),
                "spent_usd": round(apify_spent, 4),
                "budget_usd": apify_budget,
                "utilization_pct": round((apify_spent / apify_budget) * 100, 2) if apify_budget else 0.0,
            },
        },
    }


@router.get("/top-angles")
async def get_top_angles_endpoint(
    platform: str,
    limit: int = 5,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    """Top N angles by 30-day response rate for one platform -- the same
    ranking that feeds the Scout-prompt feedback hint (PRD V7 §5.7)."""
    org_id = session["org_id"]
    ranked = await top_angles(db, org_id, platform, limit=limit)
    return [{"angle": name, "response_rate": round(rate, 2)} for name, rate in ranked]
