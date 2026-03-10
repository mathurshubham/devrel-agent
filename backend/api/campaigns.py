from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List
import re
from datetime import datetime, timezone

from backend.database import get_db
from backend.models import Campaign, CampaignStatus, RedditAccount
from backend.schemas import (
    CampaignCreate, CampaignUpdate, CampaignResponse,
    RuleTestRequest, RuleTestResponse, RuleTestResult
)
from backend.utils.auth import get_current_session
from backend.utils.audit import write_audit_log
from backend.limiter import limiter

router = APIRouter(prefix="/api/campaigns", tags=["Campaigns"])

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
        **payload.dict(),
        org_id=org_id,
        status=CampaignStatus.ACTIVE
    )
    db.add(new_campaign)
    await db.commit()
    await db.refresh(new_campaign)
    
    await write_audit_log(
        db, org_id, 
        action='CAMPAIGN_CREATED', 
        details={'campaign_id': new_campaign.id, 'name': new_campaign.name},
        user_id=session["user_id"]
    )
    
    return new_campaign

@router.get("/{id}", response_model=CampaignResponse)
async def get_campaign(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]
    campaign = await db.get(Campaign, id)
    if not campaign or campaign.org_id != org_id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign

@router.patch("/{id}", response_model=CampaignResponse)
async def update_campaign(
    id: int,
    payload: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]
    campaign = await db.get(Campaign, id)
    if not campaign or campaign.org_id != org_id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(campaign, key, value)
    
    await db.commit()
    await db.refresh(campaign)
    
    await write_audit_log(
        db, org_id, 
        action='CAMPAIGN_UPDATED', 
        details={'campaign_id': campaign.id, 'changes': list(update_data.keys())},
        user_id=session["user_id"]
    )
    
    return campaign

@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]
    campaign = await db.get(Campaign, id)
    if not campaign or campaign.org_id != org_id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    await db.delete(campaign)
    await db.commit()
    
    await write_audit_log(
        db, org_id, 
        action='CAMPAIGN_DELETED', 
        details={'campaign_id': id, 'name': campaign.name},
        user_id=session["user_id"]
    )
    return None

@router.post("/{id}/test-rules", response_model=RuleTestResponse)
@limiter.limit("10/minute")
async def test_campaign_rules(
    id: int,
    payload: RuleTestRequest,
    request: Request, # Required by slowapi
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Dry-run keyword matching logic against provided sample text.
    Supports 'regex:' prefix for keywords.
    """
    org_id = session["org_id"]
    campaign = await db.get(Campaign, id)
    if not campaign or campaign.org_id != org_id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    text = payload.sample_text
    matched = []
    
    # Regex matching logic as per TRD 4.3 and scraper.py
    for kw in campaign.keywords:
        if kw.startswith("regex:"):
            pattern = kw[6:]
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    matched.append(kw)
            except re.error:
                # Silently ignore invalid regex during test
                pass
        else:
            if kw.lower() in text.lower():
                matched.append(kw)
    
    # Construct a single result for the provided sample text
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
        subreddit=campaign.subreddit_name,
        posts_tested=1,
        results=[result]
    )
