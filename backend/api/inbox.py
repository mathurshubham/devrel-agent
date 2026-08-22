from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from backend.database import get_db
from backend.models import DraftReply, DraftStatus, PlatformEnum, PostedHistory
from backend.schemas import (
    DraftReplyResponse, DraftEditRequest, DraftRejectRequest,
    DraftConfirmPostedRequest, DraftOpenCopyResponse, DraftLockResponse,
)
from backend.utils.auth import get_current_session
from backend.utils.audit import write_audit_log

router = APIRouter(prefix="/api/inbox", tags=["Inbox"])

LOCK_DURATION = timedelta(minutes=15)


async def _get_org_draft(db: AsyncSession, org_id: int, draft_id: int) -> DraftReply:
    """Fetch a draft, scoped to the caller's org. 404s if it belongs to another org."""
    draft = await db.get(DraftReply, draft_id)
    if not draft or draft.org_id != org_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.get("/drafts", response_model=List[DraftReplyResponse])
async def list_drafts(
    campaign_id: Optional[int] = None,
    status: Optional[DraftStatus] = None,
    platform: Optional[PlatformEnum] = None,
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Fetch drafts for HITL review. Filterable by campaign, status, platform,
    and free-text query `q` (trigram ILIKE over original_content/ai_draft_text,
    backed by the GIN gin_trgm_ops indexes on draft_replies).
    """
    org_id = session["org_id"]

    stmt = select(DraftReply).where(DraftReply.org_id == org_id)

    if campaign_id:
        stmt = stmt.where(DraftReply.campaign_id == campaign_id)
    if platform:
        stmt = stmt.where(DraftReply.platform == platform)
    if status:
        stmt = stmt.where(DraftReply.status == status)
    else:
        stmt = stmt.where(DraftReply.status == DraftStatus.PENDING)
    if q:
        like_pattern = f"%{q}%"
        stmt = stmt.where(
            DraftReply.original_content.ilike(like_pattern) | DraftReply.ai_draft_text.ilike(like_pattern)
        )

    stmt = stmt.order_by(DraftReply.created_at.desc())

    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/drafts/{id}/lock", response_model=DraftLockResponse)
async def lock_draft(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Atomic locking to prevent simultaneous editing. Lock lasts 15 minutes."""
    org_id = session["org_id"]
    user_id = session["user_id"]

    draft = await _get_org_draft(db, org_id, id)

    now = datetime.now(timezone.utc)
    if draft.locked_by_user_id and draft.locked_by_user_id != user_id:
        locked_at = draft.locked_at
        if locked_at and locked_at.tzinfo is None:
            locked_at = locked_at.replace(tzinfo=timezone.utc)
        if locked_at and (now - locked_at) < LOCK_DURATION:
            raise HTTPException(status_code=409, detail="Draft is currently locked by another user")

    draft.locked_by_user_id = user_id
    draft.locked_at = now
    expires_at = now + LOCK_DURATION

    await db.commit()

    return {"status": "locked", "expires_at": expires_at}


@router.patch("/drafts/{id}", response_model=DraftReplyResponse)
async def edit_draft(
    id: int,
    payload: DraftEditRequest,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Edit the AI-generated draft text before copying it out."""
    org_id = session["org_id"]

    draft = await _get_org_draft(db, org_id, id)
    draft.ai_draft_text = payload.ai_draft_text

    await write_audit_log(
        db, org_id,
        action='DRAFT_EDITED',
        details={'draft_id': id},
        user_id=session["user_id"]
    )

    await db.commit()
    await db.refresh(draft)
    return draft


@router.post("/drafts/{id}/open-copy", response_model=DraftOpenCopyResponse)
async def open_copy_draft(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Human-in-the-loop hand-off: marks the draft AWAITING_CONFIRM and returns
    the text to copy plus the target URL to open, so the reviewer can post it
    manually on the source platform.
    """
    org_id = session["org_id"]

    draft = await _get_org_draft(db, org_id, id)
    draft.status = DraftStatus.AWAITING_CONFIRM

    await write_audit_log(
        db, org_id,
        action='DRAFT_OPEN_COPY',
        details={'draft_id': id},
        user_id=session["user_id"]
    )

    await db.commit()

    return {
        "clipboard_text": draft.ai_draft_text or "",
        "reply_target_url": draft.reply_target_url or draft.url,
    }


@router.post("/drafts/{id}/confirm-posted", response_model=DraftReplyResponse)
async def confirm_posted_draft(
    id: int,
    payload: DraftConfirmPostedRequest,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Confirms the reviewer actually posted the reply. Records posted_history for idempotency."""
    org_id = session["org_id"]

    draft = await _get_org_draft(db, org_id, id)
    draft.status = DraftStatus.POSTED
    draft.posted_at_source = datetime.now(timezone.utc)
    if payload.live_url:
        draft.live_url = payload.live_url

    db.add(PostedHistory(org_id=org_id, platform=draft.platform, post_id=draft.post_id))

    await write_audit_log(
        db, org_id,
        action='DRAFT_CONFIRMED_POSTED',
        details={'draft_id': id, 'live_url': payload.live_url},
        user_id=session["user_id"]
    )

    await db.commit()
    await db.refresh(draft)
    return draft


@router.post("/drafts/{id}/unconfirm", response_model=DraftReplyResponse)
async def unconfirm_draft(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Reverts an AWAITING_CONFIRM draft back to PENDING (reviewer changed their mind)."""
    org_id = session["org_id"]

    draft = await _get_org_draft(db, org_id, id)
    draft.status = DraftStatus.PENDING

    await write_audit_log(
        db, org_id,
        action='DRAFT_UNCONFIRMED',
        details={'draft_id': id},
        user_id=session["user_id"]
    )

    await db.commit()
    await db.refresh(draft)
    return draft


@router.post("/drafts/{id}/reject", response_model=DraftReplyResponse)
async def reject_draft(
    id: int,
    payload: DraftRejectRequest,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]

    draft = await _get_org_draft(db, org_id, id)
    draft.status = DraftStatus.REJECTED
    draft.reject_reason = payload.reason

    await write_audit_log(
        db, org_id,
        action='DRAFT_REJECTED',
        details={'draft_id': id, 'reason': payload.reason},
        user_id=session["user_id"]
    )

    await db.commit()
    await db.refresh(draft)
    return draft


@router.post("/drafts/{id}/ignore", response_model=DraftReplyResponse)
async def ignore_draft(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]

    draft = await _get_org_draft(db, org_id, id)
    draft.status = DraftStatus.IGNORED

    await write_audit_log(
        db, org_id,
        action='DRAFT_IGNORED',
        details={'draft_id': id},
        user_id=session["user_id"]
    )

    await db.commit()
    await db.refresh(draft)
    return draft
