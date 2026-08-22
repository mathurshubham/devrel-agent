"""Analyst pipeline API (PRD V7 §5.6): run trigger/status, Intel Briefs,
pillar-momentum forecast, and the org-scoped watch-list/competitor tables
that feed the pipeline's triage/cluster steps.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.celery_app import celery_app
from backend.database import get_db
from backend.models import AnalystRun, Competitor, IntelBrief, TargetAuthor, TopicCluster
from backend.pipeline.analyst_graph import (
    NON_TERMINAL_RUN_STATUSES,
    current_week_of,
    non_stale_non_terminal_filter,
)
from backend.schemas import (
    AnalystRunResponse,
    CompetitorCreate,
    CompetitorResponse,
    IntelBriefDetail,
    IntelBriefSummary,
    TargetAuthorCreate,
    TargetAuthorResponse,
)
from backend.utils.audit import write_audit_log
from backend.utils.auth import get_current_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analyst", tags=["Analyst"])


def _run_to_response(run: AnalystRun) -> AnalystRunResponse:
    return AnalystRunResponse(
        run_id=run.id,
        status=run.status,
        week_of=run.week_of,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


# ---------------------------------------------------------------------------
# Run trigger / status
# ---------------------------------------------------------------------------


@router.post("/run", response_model=AnalystRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_analyst_run(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    """On-demand Analyst run. Works regardless of ``analyst_enabled`` -- that
    flag only gates the weekly beat tick. 409s if this org already has a
    run in flight."""
    org_id = session["org_id"]

    # Only a genuinely in-flight run blocks a new one -- a RUNNING row
    # older than the stale-run threshold is a wedged run (see
    # backend.pipeline.analyst_graph.non_stale_non_terminal_filter), not a
    # real in-progress run, and must not permanently 409 every future
    # trigger for this org. ``.limit(1)`` + ``scalars().first()`` since
    # nothing here guarantees at most one non-terminal row.
    existing = (
        await db.execute(
            select(AnalystRun)
            .where(AnalystRun.org_id == org_id)
            .where(non_stale_non_terminal_filter())
            .order_by(AnalystRun.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="An analyst run is already in progress for this org")

    week_of = current_week_of()
    run = AnalystRun(org_id=org_id, week_of=week_of, status="RUNNING", started_at=datetime.now(timezone.utc))
    db.add(run)
    await db.flush()

    await write_audit_log(
        db, org_id,
        action="ANALYST_RUN_TRIGGERED",
        details={"run_id": run.id, "week_of": week_of.isoformat()},
        user_id=session["user_id"],
    )

    await db.commit()
    await db.refresh(run)

    celery_app.send_task(
        "backend.tasks.workers.analyst_task", args=[org_id, run.id, week_of.isoformat()]
    )

    return _run_to_response(run)


@router.get("/status", response_model=AnalystRunResponse)
async def get_analyst_status(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    """The org's most recent Analyst run, or IDLE if none has ever run."""
    org_id = session["org_id"]
    run = (
        await db.execute(
            select(AnalystRun)
            .where(AnalystRun.org_id == org_id)
            .order_by(AnalystRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not run:
        return AnalystRunResponse(run_id=None, status="IDLE", week_of=None)
    return _run_to_response(run)


# ---------------------------------------------------------------------------
# Intel Briefs
# ---------------------------------------------------------------------------


@router.get("/briefs", response_model=List[IntelBriefSummary])
async def list_briefs(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    org_id = session["org_id"]
    rows = (
        await db.execute(
            select(IntelBrief).where(IntelBrief.org_id == org_id).order_by(IntelBrief.week_of.desc())
        )
    ).scalars().all()
    return rows


@router.get("/briefs/latest", response_model=IntelBriefDetail)
async def get_latest_brief(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    org_id = session["org_id"]
    row = (
        await db.execute(
            select(IntelBrief)
            .where(IntelBrief.org_id == org_id)
            .order_by(IntelBrief.week_of.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="No intel briefs found")
    return row


@router.get("/briefs/{brief_id}", response_model=IntelBriefDetail)
async def get_brief(
    brief_id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    org_id = session["org_id"]
    row = await db.get(IntelBrief, brief_id)
    if not row or row.org_id != org_id:
        raise HTTPException(status_code=404, detail="Brief not found")
    return row


# ---------------------------------------------------------------------------
# Pillar-momentum forecast
# ---------------------------------------------------------------------------


@router.get("/forecast")
async def get_pillar_forecast(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    """Derives pillar momentum from the org's last 4 weeks of TopicClusters:
    trending (rising), declining, and stable pillars + recommended focus."""
    org_id = session["org_id"]
    this_monday = current_week_of()
    weeks = [this_monday - timedelta(days=7 * i) for i in range(4)]

    # A given (org, week) can have more than one AnalystRun row (a
    # re-trigger, a retried run that raced a completed one, ...) --
    # aggregating TopicClusters across every run for that week would
    # double (or triple, ...) its pillar counts. Only the latest COMPLETED
    # run per week feeds the forecast.
    latest_completed_run = (
        select(AnalystRun.week_of, func.max(AnalystRun.id).label("run_id"))
        .where(
            AnalystRun.org_id == org_id,
            AnalystRun.week_of.in_(weeks),
            AnalystRun.status == "COMPLETED",
        )
        .group_by(AnalystRun.week_of)
        .subquery()
    )

    rows = (
        await db.execute(
            select(TopicCluster.pillar, TopicCluster.count, latest_completed_run.c.week_of)
            .join(latest_completed_run, latest_completed_run.c.run_id == TopicCluster.run_id)
        )
    ).all()

    by_week: dict[str, dict[str, int]] = defaultdict(dict)
    for pillar, count, week_of in rows:
        by_week[week_of.isoformat()][pillar] = by_week[week_of.isoformat()].get(pillar, 0) + count

    sorted_weeks = sorted(by_week.keys())
    all_pillars = {p for wk in by_week.values() for p in wk if p != "OTHER"}
    pillar_series = {p: [by_week[w].get(p, 0) for w in sorted_weeks] for p in all_pillars}

    trending, declining, stable = [], [], []
    for pillar, series in pillar_series.items():
        if len(series) < 2:
            stable.append({"pillar": pillar, "series": series})
            continue
        recent, prev = series[-1], series[-2]
        if recent > prev:
            trending.append({"pillar": pillar, "series": series, "delta": recent - prev})
        elif recent < prev:
            declining.append({"pillar": pillar, "series": series, "delta": recent - prev})
        else:
            stable.append({"pillar": pillar, "series": series})

    trending.sort(key=lambda x: x["delta"], reverse=True)
    declining.sort(key=lambda x: x["delta"])

    return {
        "weeks_analyzed": sorted_weeks,
        "trending": trending,
        "declining": declining,
        "stable": stable,
        "recommended_focus": [t["pillar"] for t in trending[:3]],
    }


# ---------------------------------------------------------------------------
# TargetAuthor CRUD (watch-list)
# ---------------------------------------------------------------------------


@router.get("/authors", response_model=List[TargetAuthorResponse])
async def list_authors(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    org_id = session["org_id"]
    rows = (
        await db.execute(select(TargetAuthor).where(TargetAuthor.org_id == org_id).order_by(TargetAuthor.id))
    ).scalars().all()
    return rows


@router.post("/authors", response_model=TargetAuthorResponse, status_code=status.HTTP_201_CREATED)
async def create_author(
    payload: TargetAuthorCreate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    org_id = session["org_id"]
    row = TargetAuthor(org_id=org_id, **payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/authors/{author_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_author(
    author_id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    org_id = session["org_id"]
    row = await db.get(TargetAuthor, author_id)
    if not row or row.org_id != org_id:
        raise HTTPException(status_code=404, detail="Author not found")
    await db.delete(row)
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# Competitor CRUD
# ---------------------------------------------------------------------------


@router.get("/competitors", response_model=List[CompetitorResponse])
async def list_competitors(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    org_id = session["org_id"]
    rows = (
        await db.execute(select(Competitor).where(Competitor.org_id == org_id).order_by(Competitor.id))
    ).scalars().all()
    return rows


@router.post("/competitors", response_model=CompetitorResponse, status_code=status.HTTP_201_CREATED)
async def create_competitor(
    payload: CompetitorCreate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    org_id = session["org_id"]
    row = Competitor(org_id=org_id, **payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/competitors/{competitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_competitor(
    competitor_id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session),
):
    org_id = session["org_id"]
    row = await db.get(Competitor, competitor_id)
    if not row or row.org_id != org_id:
        raise HTTPException(status_code=404, detail="Competitor not found")
    await db.delete(row)
    await db.commit()
    return None
