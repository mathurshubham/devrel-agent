from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models import User, UserRole, Organization
from backend.utils.audit import write_audit_log

router = APIRouter()

async def get_super_admin(request: Request):
    """
    Dependency to verify if the requesting user is a SUPER_ADMIN.
    Assumes request.state.user is populated (e.g. by auth middleware).
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    async with AsyncSession(request.state.db_engine) as session: # Example if using engine directly, but safer to use get_db pattern
        # For simplicity and consistency with existing code, we use dependency injection normally, 
        # but here we might need to check the DB.
        pass

    # In a real Clerk-integrated app, we'd check the User model synced via webhooks.
    # For now, we assume provide a stub that checks the User record.
    return True # Placeholder for actual auth check logic

@router.post("/promote/{user_id}")
async def promote_to_super_admin(user_id: int, db: AsyncSession = Depends(get_db)):
    """Promote a specific user to SUPER_ADMIN role."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.role = UserRole.SUPER_ADMIN
    
    await write_audit_log(
        db,
        org_id=user.org_id,
        user_id=None, # System action
        action="SUPER_ADMIN_PROMOTED",
        details={"promoted_user_id": user_id, "email": user.email}
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
