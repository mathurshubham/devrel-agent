from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from backend.models import AuditLog

async def write_audit_log(
    db: AsyncSession, 
    org_id: int, 
    action: str, 
    details: dict, 
    user_id: Optional[int] = None
):
    """
    Writes an immutable audit log entry.
    """
    log = AuditLog(
        org_id=org_id,
        user_id=user_id,
        action=action,
        details=details
    )
    db.add(log)
