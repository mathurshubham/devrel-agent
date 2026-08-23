"""DB-backed prompt-corpus lookups for the reply pipeline (PRD V7 §5.5).

Org-specific ``PromptTemplate`` rows (``org_id = <org>``) win over the
system defaults (``org_id IS NULL``) for the same ``name`` -- the "copy on
customize" model from the PRD.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import DraftReply, DraftStatus, EngagementOutcome, PromptTemplate, PromptType


@dataclass
class AngleTemplate:
    name: str
    content: str
    version: int
    org_id: Optional[int]


async def get_angle_templates(db: AsyncSession, org_id: int, platform: str) -> dict[str, AngleTemplate]:
    """Angle name -> template, org-specific rows winning over system defaults."""
    stmt = select(PromptTemplate).where(
        PromptTemplate.type == PromptType.ANGLE,
        (PromptTemplate.org_id == org_id) | (PromptTemplate.org_id.is_(None)),
        (PromptTemplate.platform == platform) | (PromptTemplate.platform.is_(None)),
    )
    rows = (await db.execute(stmt)).scalars().all()

    out: dict[str, AngleTemplate] = {}
    for row in rows:
        existing = out.get(row.name)
        # Prefer an org-specific row over a system default for the same name.
        if existing is not None and existing.org_id is not None and row.org_id is None:
            continue
        out[row.name] = AngleTemplate(
            name=row.name, content=row.content, version=row.version, org_id=row.org_id
        )
    return out


async def get_master_context_template(
    db: AsyncSession, org_id: int, platform: str
) -> Optional[AngleTemplate]:
    stmt = (
        select(PromptTemplate)
        .where(
            PromptTemplate.type == PromptType.MASTER_CONTEXT,
            (PromptTemplate.org_id == org_id) | (PromptTemplate.org_id.is_(None)),
            (PromptTemplate.platform == platform) | (PromptTemplate.platform.is_(None)),
        )
        .order_by(PromptTemplate.org_id.isnot(None).desc())
    )
    row = (await db.execute(stmt)).scalars().first()
    if not row:
        return None
    return AngleTemplate(name=row.name, content=row.content, version=row.version, org_id=row.org_id)


_TOP_ANGLES_LOOKBACK_DAYS = 30
_TOP_ANGLES_LIMIT = 3


async def top_angles(
    db: AsyncSession, org_id: int, platform: str, *, limit: int = _TOP_ANGLES_LIMIT
) -> list[tuple[str, float]]:
    """``[(angle_name, response_rate), ...]`` ranked best-first over the last
    30 days, ``response_rate`` = fraction of that angle's POSTED drafts with
    ``EngagementOutcome.got_response``. Shared by the Scout-prompt feedback
    hint below and ``GET /api/analytics/top-angles`` (PRD V7 §5.7)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_TOP_ANGLES_LOOKBACK_DAYS)

    stmt = (
        select(DraftReply.angle_name, EngagementOutcome.got_response)
        .join(EngagementOutcome, EngagementOutcome.draft_id == DraftReply.id)
        .where(
            DraftReply.org_id == org_id,
            DraftReply.platform == platform,
            DraftReply.status == DraftStatus.POSTED,
            DraftReply.angle_name.is_not(None),
            EngagementOutcome.checked_at >= cutoff,
        )
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    totals: dict[str, list[int]] = defaultdict(list)
    for angle_name, got_response in rows:
        totals[angle_name].append(1 if got_response else 0)

    return sorted(
        ((name, sum(vals) / len(vals)) for name, vals in totals.items()),
        key=lambda pair: pair[1],
        reverse=True,
    )[:limit]


async def get_top_angles_hint(db: AsyncSession, org_id: int, platform: str) -> str:
    """Scout-prompt hint naming the best-performing angles over the last 30 days.

    Ported from social-agent's ``routers/pipeline.py::_get_top_angles_hint``,
    adapted to the V7 schema: "performance" is approximated from
    ``EngagementOutcome.got_response`` on this org+platform's drafts (the
    MVP scored against a bespoke ``total_score`` column that V7 does not
    have). Returns "" when there is nothing to hint at yet.
    """
    ranked = await top_angles(db, org_id, platform)
    if not ranked or ranked[0][1] <= 0:
        return ""

    top_str = ", ".join(name for name, _ in ranked)
    return (
        f"\n\nHINT: Based on recent engagement, these angles have performed best: "
        f"{top_str}. Prefer them when posts are roughly equal."
    )
