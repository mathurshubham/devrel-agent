"""Analytics API (PRD V7 §5.7): angle leaderboard, platform performance,
draft totals + reject-reason breakdown, and spend meters (LLM + Apify).
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.ingestion.service import get_month_spend_usd, monthly_budget_usd
from backend.models import DraftReply, DraftStatus, EngagementOutcome, OrgLLMConfig, PlatformEnum
from backend.pipeline.templates import top_angles
from backend.utils.auth import get_current_session
from backend.utils.cost_guard import _daily_tokens_key, _monthly_cost_key
from backend.utils.org_lookups import get_org_settings
from backend.utils.redis_dep import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

#: Default/max lookback window for /summary -- unbounded meant loading
#: every DraftReply (and every EngagementOutcome for every draft) the org
#: has ever had into memory on every request.
_DEFAULT_SUMMARY_LOOKBACK_DAYS = 90
_MAX_SUMMARY_LOOKBACK_DAYS = 365


@router.get("/summary")
async def get_analytics_summary(
    days: int = Query(_DEFAULT_SUMMARY_LOOKBACK_DAYS, ge=1, le=_MAX_SUMMARY_LOOKBACK_DAYS),
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
    redis_client=Depends(get_redis),
):
    """Angle leaderboard (per platform), platform performance, draft totals
    + reject-reason breakdown, and LLM/Apify spend meters, over the last
    ``days`` days (default 90).

    Every count/sum below is computed SQL-side (``GROUP BY``, a window
    function for "the latest EngagementOutcome capture per draft") rather
    than loading every ``DraftReply``/``EngagementOutcome`` row for the org
    into Python -- the result cardinality is bounded by the number of
    distinct (platform, angle, status) combinations, not by how many drafts
    the org has ever had.
    """
    org_id = session["org_id"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # ── Totals + reject-reason breakdown ────────────────────────────────
    totals_rows = (
        await db.execute(
            select(DraftReply.status, DraftReply.reject_reason, func.count())
            .where(DraftReply.org_id == org_id, DraftReply.created_at >= cutoff)
            .group_by(DraftReply.status, DraftReply.reject_reason)
        )
    ).all()

    total_drafted = 0
    total_posted = 0
    total_rejected = 0
    reject_reasons: Counter = Counter()
    for status_val, reject_reason, cnt in totals_rows:
        total_drafted += cnt
        if status_val == DraftStatus.POSTED:
            total_posted += cnt
        elif status_val == DraftStatus.REJECTED:
            total_rejected += cnt
            reject_reasons[reject_reason or "unspecified"] += cnt

    # ── Drafted/posted/rejected per (platform, angle) -- platform-level
    # totals are just this summed over angle, so one grouped query covers
    # both the angle leaderboard and platform-performance counts. ───────
    counts_rows = (
        await db.execute(
            select(DraftReply.platform, DraftReply.angle_name, DraftReply.status, func.count())
            .where(DraftReply.org_id == org_id, DraftReply.created_at >= cutoff)
            .group_by(DraftReply.platform, DraftReply.angle_name, DraftReply.status)
        )
    ).all()

    angle_stats: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"drafted": 0, "posted": 0, "engagement_sum": 0, "engagement_n": 0}
    )
    platform_stats: dict[str, dict] = defaultdict(
        lambda: {"drafted": 0, "posted": 0, "rejected": 0, "engagement_sum": 0, "engagement_n": 0}
    )

    for platform_val, angle_name, status_val, cnt in counts_rows:
        platform = platform_val.value if platform_val else "UNKNOWN"
        angle = angle_name or "Unknown"
        angle_stats[(platform, angle)]["drafted"] += cnt
        platform_stats[platform]["drafted"] += cnt
        if status_val == DraftStatus.POSTED:
            angle_stats[(platform, angle)]["posted"] += cnt
            platform_stats[platform]["posted"] += cnt
        elif status_val == DraftStatus.REJECTED:
            platform_stats[platform]["rejected"] += cnt

    # ── Engagement: the highest ``hours_after`` capture per draft (a later
    # re-scrape supersedes an earlier one), summed per (platform, angle)
    # for POSTED drafts -- a window function picks "latest capture per
    # draft" SQL-side instead of fetching every outcome row. Platform-level
    # engagement is this summed over angle, same as the counts above. ───
    latest_capture_rank = (
        func.row_number()
        .over(partition_by=EngagementOutcome.draft_id, order_by=EngagementOutcome.hours_after.desc())
        .label("rn")
    )
    ranked_outcomes = (
        select(
            EngagementOutcome.draft_id.label("draft_id"),
            (
                func.coalesce(EngagementOutcome.reactions, 0)
                + func.coalesce(EngagementOutcome.replies, 0)
                + func.coalesce(EngagementOutcome.reposts, 0)
            ).label("engagement"),
            latest_capture_rank,
        )
    ).subquery()
    best_outcome = (
        select(ranked_outcomes.c.draft_id, ranked_outcomes.c.engagement)
        .where(ranked_outcomes.c.rn == 1)
    ).subquery()

    engagement_rows = (
        await db.execute(
            select(
                DraftReply.platform,
                DraftReply.angle_name,
                func.sum(best_outcome.c.engagement),
                func.count(),
            )
            .join(best_outcome, best_outcome.c.draft_id == DraftReply.id)
            .where(
                DraftReply.org_id == org_id,
                DraftReply.created_at >= cutoff,
                DraftReply.status == DraftStatus.POSTED,
            )
            .group_by(DraftReply.platform, DraftReply.angle_name)
        )
    ).all()

    for platform_val, angle_name, engagement_sum, engagement_n in engagement_rows:
        platform = platform_val.value if platform_val else "UNKNOWN"
        angle = angle_name or "Unknown"
        engagement_sum = int(engagement_sum or 0)
        engagement_n = int(engagement_n or 0)
        angle_stats[(platform, angle)]["engagement_sum"] += engagement_sum
        angle_stats[(platform, angle)]["engagement_n"] += engagement_n
        platform_stats[platform]["engagement_sum"] += engagement_sum
        platform_stats[platform]["engagement_n"] += engagement_n

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
    platform: PlatformEnum,
    limit: int = Query(5, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    """Top N angles by 30-day response rate for one platform -- the same
    ranking that feeds the Scout-prompt feedback hint (PRD V7 §5.7).

    ``platform`` is validated against ``PlatformEnum`` (a bogus value 422s
    instead of silently falling through to "no rows match, empty result")
    and ``limit`` is bounded 1..50.
    """
    org_id = session["org_id"]
    ranked = await top_angles(db, org_id, platform.value, limit=limit)
    return [{"angle": name, "response_rate": round(rate, 2)} for name, rate in ranked]
