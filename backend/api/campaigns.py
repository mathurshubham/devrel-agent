from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import re
from datetime import datetime, timezone

from backend.database import get_db
from backend.models import Campaign, CampaignStatus
from backend.schemas import (
    CampaignCreate, CampaignUpdate, CampaignResponse,
    RuleTestRequest, RuleTestResponse, RuleTestResult
)
from backend.utils.auth import get_current_session
from backend.utils.audit import write_audit_log
from backend.limiter import limiter
from backend.tasks.scheduler import enqueue_campaign, enqueue_campaign_now, remove_campaign

router = APIRouter(prefix="/api/campaigns", tags=["Campaigns"])


async def _get_org_campaign(db: AsyncSession, org_id: int, campaign_id: int) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.org_id != org_id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.get("", response_model=List[CampaignResponse])
async def list_campaigns(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]
    stmt = select(Campaign).where(Campaign.org_id == org_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]
    new_campaign = Campaign(
        **payload.model_dump(),
        org_id=org_id,
        status=CampaignStatus.ACTIVE
    )
    db.add(new_campaign)
    await db.flush()
    await db.refresh(new_campaign)

    # Audit log BEFORE the final commit so it's not silently lost.
    await write_audit_log(
        db, org_id,
        action='CAMPAIGN_CREATED',
        details={'campaign_id': new_campaign.id, 'name': new_campaign.name},
        user_id=session["user_id"]
    )

    await db.commit()

    # New campaigns start ACTIVE, so put them on the scheduler due
    # immediately -- no reason to make the org wait a full poll cycle for
    # its first check.
    await enqueue_campaign_now(new_campaign.id)

    return new_campaign


@router.get("/{id}", response_model=CampaignResponse)
async def get_campaign(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    return await _get_org_campaign(db, session["org_id"], id)


@router.patch("/{id}", response_model=CampaignResponse)
async def update_campaign(
    id: int,
    payload: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]
    campaign = await _get_org_campaign(db, org_id, id)

    previous_status = campaign.status
    previous_poll_frequency = campaign.poll_frequency_minutes
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(campaign, key, value)

    await write_audit_log(
        db, org_id,
        action='CAMPAIGN_UPDATED',
        details={'campaign_id': campaign.id, 'changes': list(update_data.keys())},
        user_id=session["user_id"]
    )

    await db.commit()
    await db.refresh(campaign)

    # Keep the Redis scheduler ZSET in sync with the campaign's status/
    # frequency -- but only touch it when one of those two actually changed,
    # so an unrelated field edit (e.g. name, keywords) doesn't reset an
    # in-flight poll schedule.
    status_changed = campaign.status != previous_status
    frequency_changed = campaign.poll_frequency_minutes != previous_poll_frequency

    if campaign.status == CampaignStatus.ACTIVE and (status_changed or frequency_changed):
        await enqueue_campaign(campaign.id, campaign.poll_frequency_minutes)
    elif previous_status == CampaignStatus.ACTIVE and campaign.status != CampaignStatus.ACTIVE:
        await remove_campaign(campaign.id)

    return campaign


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]
    campaign = await _get_org_campaign(db, org_id, id)
    campaign_name = campaign.name

    await write_audit_log(
        db, org_id,
        action='CAMPAIGN_DELETED',
        details={'campaign_id': id, 'name': campaign_name},
        user_id=session["user_id"]
    )

    await db.delete(campaign)
    await db.commit()

    await remove_campaign(id)
    return None


@router.post("/{id}/test-rules", response_model=RuleTestResponse)
@limiter.limit("10/minute")
async def test_campaign_rules(
    id: int,
    payload: RuleTestRequest,
    request: Request,  # Required by slowapi
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Dry-run keyword matching logic against provided sample text. Supports 'regex:' prefix."""
    campaign = await _get_org_campaign(db, session["org_id"], id)

    text = payload.sample_text
    matched = []

    for kw in campaign.keywords:
        if kw.startswith("regex:"):
            pattern = kw[6:]
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    matched.append(kw)
            except re.error:
                pass
        else:
            if kw.lower() in text.lower():
                matched.append(kw)

    result = RuleTestResult(
        post_title="Sample Text Test",
        post_url="#",
        matched_keywords=matched,
        confidence_score=1.0 if matched else 0.0,
        would_trigger=len(matched) > 0,
        safety_override=False,
        triage_reasoning=f"Matched keywords: {', '.join(matched)}" if matched else "No keywords matched."
    )

    return RuleTestResponse(
        tested_at=datetime.now(timezone.utc),
        platform=campaign.platform,
        posts_tested=1,
        results=[result]
    )
