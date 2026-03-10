import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from svix.webhooks import Webhook

from backend.database import SessionLocal
from backend.models import User, Organization, ProcessedWebhookEvent, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])

async def get_db():
    async with SessionLocal() as session:
        yield session

@router.post("/clerk")
async def clerk_webhook(
    request: Request,
    svix_id: str = Header(None, alias="svix-id"),
    svix_timestamp: str = Header(None, alias="svix-timestamp"),
    svix_signature: str = Header(None, alias="svix-signature"),
    db: AsyncSession = Depends(get_db)
):
    """
    Clerk Webhook Sync Endpoint.
    TRD Sections 3.1, 6, and 12 implementation.
    """
    WEBHOOK_SECRET = os.getenv("CLERK_WEBHOOK_SECRET")
    if not WEBHOOK_SECRET:
        logger.error("CLERK_WEBHOOK_SECRET not set")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    # 1. Replay Attack Guard (TRD Sec 3.1 & 6)
    if not svix_timestamp:
        raise HTTPException(status_code=400, detail="Missing timestamp")
    
    try:
        ts = int(svix_timestamp)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp")

    now = time.time()
    if now - ts > 300:
        logger.warning(f"Replay attack detected. Timestamp: {ts}, Now: {now}")
        raise HTTPException(status_code=400, detail="Webhook timestamp too old — replay rejected")

    # 2. HMAC Signature Verification
    body = await request.body()
    wh = Webhook(WEBHOOK_SECRET)
    try:
        # svix headers are case-sensitive and must be passed as a dict
        evt = wh.verify(body.decode(), {
            "svix-id": svix_id,
            "svix-timestamp": svix_timestamp,
            "svix-signature": svix_signature
        })
    except Exception as e:
        logger.warning(f"Invalid webhook signature: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 3. Idempotency via Database (TRD Sec 3.1 & 12)
    # INSERT ... ON CONFLICT DO NOTHING using svix-id
    processed_stmt = pg_insert(ProcessedWebhookEvent).values(
        event_id=svix_id,
        event_type=evt.get("type", "unknown"),
        processed_at=datetime.now(timezone.utc)
    ).on_conflict_do_nothing(index_elements=["event_id"])
    
    result = await db.execute(processed_stmt)
    if result.rowcount == 0:
        logger.info(f"Duplicate webhook event {svix_id} skipped.")
        return {"ok": True, "skipped": "duplicate"}

    # 4. Clerk Event Handlers
    evt_type = evt.get("type")
    data = evt.get("data", {})

    try:
        if evt_type in ["user.created", "user.updated"]:
            clerk_id = data.get("id")
            emails = data.get("email_addresses", [])
            primary_email = emails[0].get("email_address") if emails else ""
            
            user_stmt = pg_insert(User).values(
                clerk_id=clerk_id,
                email=primary_email,
                role=UserRole.MEMBER, # Default
                is_active=True
            ).on_conflict_do_update(
                index_elements=["clerk_id"],
                set_={"email": primary_email}
            )
            await db.execute(user_stmt)

        elif evt_type == "user.deleted":
            clerk_id = data.get("id")
            await db.execute(
                update(User).where(User.clerk_id == clerk_id).values(is_active=False)
            )

        elif evt_type == "organization.created":
            clerk_org_id = data.get("id")
            name = data.get("name")
            org_stmt = pg_insert(Organization).values(
                clerk_org_id=clerk_org_id,
                name=name,
                is_active=True
            ).on_conflict_do_nothing(index_elements=["clerk_org_id"])
            await db.execute(org_stmt)

        elif evt_type == "organizationMembership.created":
            clerk_org_id = data.get("organization", {}).get("id")
            clerk_user_id = data.get("public_user_data", {}).get("user_id")
            clerk_role = data.get("role") # 'org:admin' or 'org:member'
            
            # Resolve our internal org id
            org_res = await db.execute(select(Organization).filter(Organization.clerk_org_id == clerk_org_id))
            org = org_res.scalar_one_or_none()
            
            if org:
                internal_role = UserRole.ADMIN if clerk_role == "org:admin" else UserRole.MEMBER
                await db.execute(
                    update(User).where(User.clerk_id == clerk_user_id).values(
                        org_id=org.id,
                        role=internal_role
                    )
                )

        elif evt_type == "organization.deleted":
            clerk_org_id = data.get("id")
            await db.execute(
                update(Organization).where(Organization.clerk_org_id == clerk_org_id).values(is_active=False)
            )

        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Error processing Clerk event {evt_type}: {str(e)}")
        # We don't raise 500 here to avoid Clerk retrying infinitely if it's a data issue,
        # but in a real prod env we might want to fail so Clerk retries transient DB errors.
        # TRD doesn't explicitly mandate 500 on data errors, but does mandate idempotency.
        raise HTTPException(status_code=500, detail="Internal processing error")

    return {"received": True}
