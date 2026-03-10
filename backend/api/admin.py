import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models import User, UserRole, Organization
from backend.utils.audit import write_audit_log

router = APIRouter()

async def require_super_admin(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Dependency to verify if the requesting user is a SUPER_ADMIN.
    """
    clerk_id = getattr(request.state, "user_id", None)
    if not clerk_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    result = await db.execute(select(User).where(User.clerk_id == clerk_id))
    user = result.scalar_one_or_none()
    
    if not user or user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super Admin access required")
    
    return user

@router.post("/promote/{target_user_id}")
async def promote_to_super_admin(
    target_user_id: int, 
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Promote a specific user to SUPER_ADMIN role synchronously with Clerk."""
    result = await db.execute(select(User).where(User.id == target_user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 1. Update Clerk Metadata
    CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
    if not CLERK_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Clerk Secret Key not configured")

    async with httpx.AsyncClient() as client:
        # Clerk API endpoint: https://api.clerk.com/v1/users/{user_id}/metadata
        resp = await client.post(
            f"https://api.clerk.com/v1/users/{user.clerk_id}/metadata",
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
            json={
                "public_metadata": {
                    "role": "SUPER_ADMIN"
                }
            }
        )
        if resp.status_code != 200:
            logger.error(f"Failed to update Clerk metadata: {resp.text}")
            raise HTTPException(status_code=502, detail="Clerk metadata sync failed")

    # 2. Update Local DB
    user.role = UserRole.SUPER_ADMIN
    
    await write_audit_log(
        db,
        org_id=user.org_id,
        user_id=admin_user.id,
        action="SUPER_ADMIN_PROMOTED",
        details={"promoted_user_id": target_user_id, "clerk_id": user.clerk_id, "email": user.email}
    )
    
    await db.commit()
    return {"status": "success", "message": f"User {user.email} promoted to SUPER_ADMIN"}

@router.get("/organizations")
async def list_all_organizations(db: AsyncSession = Depends(get_db)):
    """Super Admin view: List all organizations on the platform."""
    result = await db.execute(select(Organization))
    orgs = result.scalars().all()
    return orgs

@router.get("/users")
async def list_all_users(db: AsyncSession = Depends(get_db)):
    """Super Admin view: List all users on the platform."""
    result = await db.execute(select(User))
    users = result.scalars().all()
    return users
