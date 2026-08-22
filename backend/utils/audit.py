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

    IMPORTANT: call this BEFORE the caller's final `await db.commit()` — it
    flushes the row into the current transaction so it commits atomically
    with the rest of the request's writes. Calling it after the final commit
    silently loses the entry (the row is added to the session but nothing
    ever persists it).
    """
    log = AuditLog(
        org_id=org_id,
        user_id=user_id,
        action=action,
        details=details
    )
    db.add(log)
    await db.flush()
