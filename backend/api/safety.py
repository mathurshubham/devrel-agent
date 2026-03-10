from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List

from backend.database import get_db
from backend.models import SubredditSafetyProfile
from backend.schemas import SubredditSafetyProfileCreate, SubredditSafetyProfileSchema
from backend.api.org import get_current_session

router = APIRouter(prefix="/api/safety", tags=["Safety Profiles"])

@router.get("/", response_model=List[SubredditSafetyProfileSchema])
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

@router.post("/", response_model=SubredditSafetyProfileSchema)
async def create_safety_profile(
    payload: SubredditSafetyProfileCreate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Create a new safety profile for a subreddit."""
    org_id = session["org_id"]
    
    # Check if exists
    existing = await db.execute(
        select(SubredditSafetyProfile).where(
            SubredditSafetyProfile.org_id == org_id,
            SubredditSafetyProfile.subreddit_name == payload.subreddit_name
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Safety profile for {payload.subreddit_name} already exists."
        )

    profile = SubredditSafetyProfile(
        **payload.model_dump(),
        org_id=org_id
    )
    db.add(profile)
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

    await db.commit()
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
    
    await db.execute(
        delete(SubredditSafetyProfile).where(
            SubredditSafetyProfile.id == profile_id,
            SubredditSafetyProfile.org_id == org_id
        )
    )
    await db.commit()
    return {"status": "deleted"}
