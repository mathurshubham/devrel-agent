from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from backend.database import get_db
from backend.models import DraftReply, DraftStatus, PlatformEnum, PostedHistory
from backend.schemas import (
    DraftReplyResponse, DraftReplyListResponse, DraftEditRequest, DraftRejectRequest,
    DraftConfirmPostedRequest, DraftOpenCopyResponse, DraftLockResponse,
)
from backend.utils.auth import get_current_session
from backend.utils.audit import write_audit_log

router = APIRouter(prefix="/api/inbox", tags=["Inbox"])

LOCK_DURATION = timedelta(minutes=15)

# ── Status machine ────────────────────────────────────────────────────────────
# PRD V7 §5.4: every mutating action on a draft is only valid from a specific
# set of source statuses. Anything else is a 409, not a silent no-op.
_EDITABLE_FROM       = {DraftStatus.PENDING, DraftStatus.AWAITING_CONFIRM}
_OPEN_COPY_FROM      = {DraftStatus.PENDING, DraftStatus.AWAITING_CONFIRM}  # retry allowed
_CONFIRM_POSTED_FROM = {DraftStatus.AWAITING_CONFIRM}
_UNCONFIRM_FROM      = {DraftStatus.AWAITING_CONFIRM}
_REJECT_FROM         = {DraftStatus.PENDING, DraftStatus.AWAITING_CONFIRM}
_IGNORE_FROM         = {DraftStatus.PENDING, DraftStatus.AWAITING_CONFIRM}
_LOCK_FROM           = {DraftStatus.PENDING, DraftStatus.AWAITING_CONFIRM}


def _require_status(draft: DraftReply, allowed: set, action: str) -> None:
    if draft.status not in allowed:
        allowed_str = ", ".join(sorted(s.value for s in allowed))
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} a draft in status {draft.status.value} (allowed: {allowed_str})",
        )


def _enforce_and_take_over_lock(draft: DraftReply, user_id: int, now: datetime) -> None:
    """
    409s if the draft is locked by a DIFFERENT user and that lock hasn't
    expired yet. Otherwise (no lock, same-user lock, or expired lock) the
    caller proceeds and takes over/refreshes the lock as of `now`.
    """
    locked_at = draft.locked_at
    if locked_at and locked_at.tzinfo is None:
        locked_at = locked_at.replace(tzinfo=timezone.utc)

    if draft.locked_by_user_id and draft.locked_by_user_id != user_id:
        if locked_at and (now - locked_at) < LOCK_DURATION:
            raise HTTPException(status_code=409, detail="Draft is currently locked by another user")

    draft.locked_by_user_id = user_id
    draft.locked_at = now


def _escape_like(value: str) -> str:
    """Escape ILIKE metacharacters (% and _) so free-text search treats them literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _get_org_draft(db: AsyncSession, org_id: int, draft_id: int) -> DraftReply:
    """Fetch a draft, scoped to the caller's org. 404s if it belongs to another org."""
    draft = await db.get(DraftReply, draft_id)
    if not draft or draft.org_id != org_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.get("/drafts", response_model=DraftReplyListResponse)
async def list_drafts(
    campaign_id: Optional[int] = None,
    status: Optional[DraftStatus] = None,
    platform: Optional[PlatformEnum] = None,
    signal_tier: Optional[str] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Fetch drafts for HITL review. Filterable by campaign, status, platform,
    signal_tier, and free-text query `q` (trigram ILIKE over
    original_content/ai_draft_text, backed by the GIN gin_trgm_ops indexes
    on draft_replies). Paginated at 50/page.
    """
    org_id = session["org_id"]
    page_size = 50

    stmt = select(DraftReply).where(DraftReply.org_id == org_id)

    if campaign_id:
        stmt = stmt.where(DraftReply.campaign_id == campaign_id)
    if platform:
        stmt = stmt.where(DraftReply.platform == platform)
    if signal_tier:
        stmt = stmt.where(DraftReply.signal_tier == signal_tier)
    if status:
        stmt = stmt.where(DraftReply.status == status)
    else:
        stmt = stmt.where(DraftReply.status == DraftStatus.PENDING)
    if q:
        like_pattern = f"%{_escape_like(q)}%"
        stmt = stmt.where(
            DraftReply.original_content.ilike(like_pattern, escape="\\")
            | DraftReply.ai_draft_text.ilike(like_pattern, escape="\\")
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        stmt.order_by(DraftReply.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(stmt)
    items = result.scalars().all()

    return {"items": items, "total": total, "page": page, "page_size": page_size}


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
    _require_status(draft, _LOCK_FROM, "lock")

    now = datetime.now(timezone.utc)
    _enforce_and_take_over_lock(draft, user_id, now)
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
    user_id = session["user_id"]

    draft = await _get_org_draft(db, org_id, id)
    _require_status(draft, _EDITABLE_FROM, "edit")
    _enforce_and_take_over_lock(draft, user_id, datetime.now(timezone.utc))

    draft.ai_draft_text = payload.ai_draft_text

    await write_audit_log(
        db, org_id,
        action='DRAFT_EDITED',
        details={'draft_id': id},
        user_id=user_id
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
    user_id = session["user_id"]

    draft = await _get_org_draft(db, org_id, id)
    _require_status(draft, _OPEN_COPY_FROM, "open-copy")
    _enforce_and_take_over_lock(draft, user_id, datetime.now(timezone.utc))

    draft.status = DraftStatus.AWAITING_CONFIRM

    await write_audit_log(
        db, org_id,
        action='DRAFT_OPEN_COPY',
        details={'draft_id': id},
        user_id=user_id
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
    user_id = session["user_id"]

    draft = await _get_org_draft(db, org_id, id)
    _require_status(draft, _CONFIRM_POSTED_FROM, "confirm-posted")
    _enforce_and_take_over_lock(draft, user_id, datetime.now(timezone.utc))

    draft.status = DraftStatus.POSTED
    draft.posted_at_source = datetime.now(timezone.utc)
    if payload.live_url:
        draft.live_url = payload.live_url

    # Idempotent: a retried/duplicate confirm-posted call for the same
    # (org, platform, post_id) must not raise an IntegrityError.
    await db.execute(
        pg_insert(PostedHistory)
        .values(org_id=org_id, platform=draft.platform, post_id=draft.post_id)
        .on_conflict_do_nothing(constraint="uq_posted_history_org_platform_post")
    )

    await write_audit_log(
        db, org_id,
        action='DRAFT_CONFIRMED_POSTED',
        details={'draft_id': id, 'live_url': payload.live_url},
        user_id=user_id
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
    user_id = session["user_id"]

    draft = await _get_org_draft(db, org_id, id)
    _require_status(draft, _UNCONFIRM_FROM, "unconfirm")
    _enforce_and_take_over_lock(draft, user_id, datetime.now(timezone.utc))

    draft.status = DraftStatus.PENDING

    await write_audit_log(
        db, org_id,
        action='DRAFT_UNCONFIRMED',
        details={'draft_id': id},
        user_id=user_id
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
    user_id = session["user_id"]

    draft = await _get_org_draft(db, org_id, id)
    _require_status(draft, _REJECT_FROM, "reject")
    _enforce_and_take_over_lock(draft, user_id, datetime.now(timezone.utc))

    draft.status = DraftStatus.REJECTED
    draft.reject_reason = payload.reason

    await write_audit_log(
        db, org_id,
        action='DRAFT_REJECTED',
        details={'draft_id': id, 'reason': payload.reason},
        user_id=user_id
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
    user_id = session["user_id"]

    draft = await _get_org_draft(db, org_id, id)
    _require_status(draft, _IGNORE_FROM, "ignore")
    _enforce_and_take_over_lock(draft, user_id, datetime.now(timezone.utc))

    draft.status = DraftStatus.IGNORED

    await write_audit_log(
        db, org_id,
        action='DRAFT_IGNORED',
        details={'draft_id': id},
        user_id=user_id
    )

    await db.commit()
    await db.refresh(draft)
    return draft
