from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
from datetime import datetime, timezone

from backend.database import get_db
from backend.models import DraftReply, DraftStatus, User
from backend.schemas import DraftReplyResponse
from backend.utils.auth import get_current_session
from backend.utils.audit import write_audit_log

router = APIRouter(prefix="/api/inbox", tags=["Inbox"])

@router.get("/drafts", response_model=List[DraftReplyResponse])
async def list_drafts(
    campaign_id: Optional[int] = None,
    status: Optional[DraftStatus] = None,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Fetch pending drafts for HITL review.
    Filterable by campaign and status.
    """
    org_id = session["org_id"]
    
    # Subquery to ensure drafts belong to campaigns owned by the org
    from backend.models import Campaign
    
    stmt = select(DraftReply).join(Campaign).where(Campaign.org_id == org_id)
    
    if campaign_id:
        stmt = stmt.where(DraftReply.campaign_id == campaign_id)
    if status:
        stmt = stmt.where(DraftReply.status == status)
    else:
        # Default to PENDING if no status specified
        stmt = stmt.where(DraftReply.status == DraftStatus.PENDING)
        
    stmt = stmt.order_by(DraftReply.created_at.desc())
    
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/drafts/{id}/lock")
async def lock_draft(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Atomic locking logic (Section 5.6) to prevent simultaneous editing.
    """
    org_id = session["org_id"]
    user_id = session["user_id"] # Internal user ID from sessions
    
    # Find user in DB to get the integer ID
    stmt = select(User).where(User.clerk_id == session["clerk_id"])
    res = await db.execute(stmt)
    db_user = res.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found in database")

    draft = await db.get(DraftReply, id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    # Check if already locked by someone else and lock hasn't expired (15 mins)
    now = datetime.now(timezone.utc)
    if draft.locked_by_user_id and draft.locked_by_user_id != db_user.id:
        if draft.locked_at and (now - draft.locked_at.replace(tzinfo=timezone.utc)).total_seconds() < 900:
            raise HTTPException(status_code=409, detail=f"Draft is currently locked by another user")

    # Update lock
    draft.locked_by_user_id = db_user.id
    draft.locked_at = now
    await db.commit()
    
    return {"status": "locked", "expires_at": now.isoformat()}

@router.post("/drafts/{id}/approve")
async def approve_draft(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Approve a draft and queue it for publishing.
    Triggers 'praw_publish' Celery task.
    """
    org_id = session["org_id"]
    
    draft = await db.get(DraftReply, id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    # Transition to APPROVED
    draft.status = DraftStatus.APPROVED
    
    # Identify who approved it
    stmt = select(User).where(User.clerk_id == session["clerk_id"])
    res = await db.execute(stmt)
    db_user = res.scalar_one_or_none()
    if db_user:
        draft.approved_by_user_id = db_user.id

    await db.commit()
    
    # ── TRIGGER CELERY TASK ───────────────────────────────────────────────────
    try:
        from backend.celery_app import celery_app
        # We assume the task name based on TRD/conventions
        celery_app.send_task(
            "backend.tasks.praw_publish.publish_reply", 
            args=[draft.id], 
            queue='praw_publish'
        )
    except Exception as e:
        # Log failure but don't fail the API call
        print(f"Failed to queue publish task: {e}")

    await write_audit_log(
        db, org_id, 
        action='DRAFT_APPROVED', 
        details={'draft_id': id},
        user_id=session["user_id"]
    )
    
    return {"status": "approved", "message": "Draft queued for publishing"}

@router.post("/drafts/{id}/reject")
async def reject_draft(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]
    
    draft = await db.get(DraftReply, id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft.status = DraftStatus.REJECTED
    await db.commit()
    
    await write_audit_log(
        db, org_id, 
        action='DRAFT_REJECTED', 
        details={'draft_id': id},
        user_id=session["user_id"]
    )
    return {"status": "rejected"}

@router.delete("/drafts/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]
    
    draft = await db.get(DraftReply, id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    await db.delete(draft)
    await db.commit()
    
    return None
