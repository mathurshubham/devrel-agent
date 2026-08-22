import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from svix.webhooks import Webhook

from backend.database import SessionLocal
from backend.models import User, Organization, OrgMembership, ProcessedWebhookEvent, UserRole

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
    """Clerk webhook sync endpoint: keeps Organization/User/OrgMembership rows in sync."""
    WEBHOOK_SECRET = os.getenv("CLERK_WEBHOOK_SECRET")
    if not WEBHOOK_SECRET:
        logger.error("CLERK_WEBHOOK_SECRET not set")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    # 1. Replay attack guard.
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

    # 2. HMAC signature verification.
    body = await request.body()
    wh = Webhook(WEBHOOK_SECRET)
    try:
        evt = wh.verify(body.decode(), {
            "svix-id": svix_id,
            "svix-timestamp": svix_timestamp,
            "svix-signature": svix_signature
        })
    except Exception as e:
        logger.warning(f"Invalid webhook signature: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 3. Idempotency via svix-id (INSERT ... ON CONFLICT DO NOTHING).
    processed_stmt = pg_insert(ProcessedWebhookEvent).values(
        svix_id=svix_id,
        processed_at=datetime.now(timezone.utc)
    ).on_conflict_do_nothing(index_elements=["svix_id"])

    result = await db.execute(processed_stmt)
    if result.rowcount == 0:
        logger.info(f"Duplicate webhook event {svix_id} skipped.")
        return {"ok": True, "skipped": "duplicate"}

    # 4. Clerk event handlers.
    evt_type = evt.get("type")
    data = evt.get("data", {})

    try:
        if evt_type in ["user.created", "user.updated"]:
            clerk_user_id = data.get("id")
            emails = data.get("email_addresses", [])
            primary_email = emails[0].get("email_address") if emails else ""

            user_stmt = pg_insert(User).values(
                clerk_user_id=clerk_user_id,
                email=primary_email,
                role=UserRole.MEMBER,
            ).on_conflict_do_update(
                index_elements=["clerk_user_id"],
                set_={"email": primary_email}
            )
            await db.execute(user_stmt)

        elif evt_type == "user.deleted":
            clerk_user_id = data.get("id")
            user_res = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
            user = user_res.scalar_one_or_none()
            if user:
                # users has no soft-delete flag in V7 — revoke org access instead.
                await db.execute(
                    OrgMembership.__table__.delete().where(OrgMembership.user_id == user.id)
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

        elif evt_type in ("organizationMembership.created", "organizationMembership.updated"):
            clerk_org_id = data.get("organization", {}).get("id")
            clerk_user_id = data.get("public_user_data", {}).get("user_id")
            clerk_role = data.get("role")  # 'org:admin' or 'org:member'

            org_res = await db.execute(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
            org = org_res.scalar_one_or_none()

            user_res = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
            user = user_res.scalar_one_or_none()

            if org and user:
                internal_role = UserRole.ADMIN if clerk_role == "org:admin" else UserRole.MEMBER
                membership_stmt = pg_insert(OrgMembership).values(
                    org_id=org.id,
                    user_id=user.id,
                    role=internal_role.value,
                ).on_conflict_do_update(
                    index_elements=["org_id", "user_id"],
                    set_={"role": internal_role.value},
                )
                await db.execute(membership_stmt)

        elif evt_type == "organizationMembership.deleted":
            clerk_org_id = data.get("organization", {}).get("id")
            clerk_user_id = data.get("public_user_data", {}).get("user_id")

            org_res = await db.execute(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
            org = org_res.scalar_one_or_none()
            user_res = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
            user = user_res.scalar_one_or_none()

            if org and user:
                await db.execute(
                    OrgMembership.__table__.delete().where(
                        OrgMembership.org_id == org.id, OrgMembership.user_id == user.id
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
        raise HTTPException(status_code=500, detail="Internal processing error")

    return {"received": True}
