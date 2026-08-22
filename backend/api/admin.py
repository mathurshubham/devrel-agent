import os
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import User, UserRole, Organization
from backend.utils.audit import write_audit_log
from backend.utils.auth import get_current_session

logger = logging.getLogger(__name__)

router = APIRouter()


async def require_super_admin(
    session: dict = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Verifies the caller's User row (not just their per-org membership role)
    has UserRole.SUPER_ADMIN. SUPER_ADMIN is only ever granted via the
    promote endpoint below — it is never derived from a Clerk claim.
    """
    user = await db.get(User, session["user_id"])
    if not user or user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super Admin access required")
    return user


@router.post("/promote/{target_user_id}")
async def promote_to_super_admin(
    target_user_id: int,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Promote a specific user to SUPER_ADMIN role, synced with Clerk metadata."""
    result = await db.execute(select(User).where(User.id == target_user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
    if not CLERK_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Clerk Secret Key not configured")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.clerk.com/v1/users/{user.clerk_user_id}/metadata",
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
            json={"public_metadata": {"role": "SUPER_ADMIN"}}
        )
        if resp.status_code != 200:
            logger.error(f"Failed to update Clerk metadata: {resp.text}")
            raise HTTPException(status_code=502, detail="Clerk metadata sync failed")

    user.role = UserRole.SUPER_ADMIN

    await write_audit_log(
        db,
        org_id=None,
        user_id=admin_user.id,
        action="SUPER_ADMIN_PROMOTED",
        details={"promoted_user_id": target_user_id, "clerk_user_id": user.clerk_user_id, "email": user.email}
    )

    await db.commit()
    return {"status": "success", "message": f"User {user.email} promoted to SUPER_ADMIN"}


@router.get("/organizations")
async def list_all_organizations(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_super_admin),
):
    """Super Admin view: list all organizations on the platform."""
    result = await db.execute(select(Organization))
    orgs = result.scalars().all()
    return orgs


@router.get("/users")
async def list_all_users(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_super_admin),
):
    """Super Admin view: list all users on the platform."""
    result = await db.execute(select(User))
    users = result.scalars().all()
    return users
