from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List

from backend.database import get_db
from backend.models import SubredditSafetyProfile
from backend.schemas import SubredditSafetyProfileCreate, SubredditSafetyProfileSchema
from backend.utils.auth import get_current_session
from backend.utils.audit import write_audit_log

router = APIRouter(prefix="/api/safety", tags=["Safety Profiles"])


@router.get("", response_model=List[SubredditSafetyProfileSchema])
async def list_safety_profiles(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """List all safety profiles for the organization."""
    org_id = session["org_id"]
    result = await db.execute(
        select(SubredditSafetyProfile).where(SubredditSafetyProfile.org_id == org_id)
    )
    return result.scalars().all()


@router.post("", response_model=SubredditSafetyProfileSchema)
async def create_safety_profile(
    payload: SubredditSafetyProfileCreate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Create a new safety profile for a subreddit."""
    org_id = session["org_id"]

    existing = await db.execute(
        select(SubredditSafetyProfile).where(
            SubredditSafetyProfile.org_id == org_id,
            SubredditSafetyProfile.subreddit == payload.subreddit
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Safety profile for {payload.subreddit} already exists."
        )

    profile = SubredditSafetyProfile(
        **payload.model_dump(),
        org_id=org_id
    )
    db.add(profile)
    try:
        await db.flush()
    except IntegrityError:
        # Race: another request created the same (org_id, subreddit) profile
        # between our pre-check above and this flush.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Safety profile for {payload.subreddit} already exists."
        )

    await write_audit_log(
        db, org_id,
        action='SAFETY_PROFILE_CREATED',
        details={'subreddit': payload.subreddit},
        user_id=session["user_id"]
    )

    await db.commit()
    await db.refresh(profile)
    return profile


@router.put("/{profile_id}", response_model=SubredditSafetyProfileSchema)
async def update_safety_profile(
    profile_id: int,
    payload: SubredditSafetyProfileCreate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Update an existing safety profile."""
    org_id = session["org_id"]

    result = await db.execute(
        select(SubredditSafetyProfile).where(
            SubredditSafetyProfile.id == profile_id,
            SubredditSafetyProfile.org_id == org_id
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    for key, value in payload.model_dump().items():
        setattr(profile, key, value)

    await write_audit_log(
        db, org_id,
        action='SAFETY_PROFILE_UPDATED',
        details={'profile_id': profile_id},
        user_id=session["user_id"]
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Safety profile for {payload.subreddit} already exists."
        )
    await db.refresh(profile)
    return profile


@router.delete("/{profile_id}")
async def delete_safety_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Delete a safety profile."""
    org_id = session["org_id"]

    result = await db.execute(
        select(SubredditSafetyProfile).where(
            SubredditSafetyProfile.id == profile_id,
            SubredditSafetyProfile.org_id == org_id
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    await write_audit_log(
        db, org_id,
        action='SAFETY_PROFILE_DELETED',
        details={'profile_id': profile_id, 'subreddit': profile.subreddit},
        user_id=session["user_id"]
    )

    await db.execute(
        delete(SubredditSafetyProfile).where(
            SubredditSafetyProfile.id == profile_id,
            SubredditSafetyProfile.org_id == org_id
        )
    )
    await db.commit()
    return {"status": "deleted"}
