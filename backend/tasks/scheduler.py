import asyncio
import logging
import os
import time
import redis.asyncio as redis
from datetime import datetime, timezone, timedelta
from typing import List

from sqlalchemy.future import select
from celery_app import celery_app

from backend.database import SessionLocal
from backend.models import Campaign, CampaignStatus, Organization, ProcessedWebhookEvent

logger = logging.getLogger(__name__)

# Redis Client for Priority Queue (Async)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL)

SCHEDULER_KEY = "campaign:scheduler"

@celery_app.task(name="tasks.scheduler.scheduler_tick", bind=True, queue="maintenance")
def scheduler_tick(self):
    """
    Celery Beat task: Drift-free polling using Redis ZSET Priority Queue.
    TRD Section 4.10 implementation.
    """
    async def _tick():
        now = time.time()
        logger.info(f"Running scheduler_tick at {now}")

        # 1. Fetch all due campaigns (score <= now)
        # Using bytes_to_str=True on client init is cleaner, but we'll decode here.
        due_ids_raw = await redis_client.zrangebyscore(SCHEDULER_KEY, 0, now)
        if not due_ids_raw:
            logger.info("No campaigns due for polling.")
            return

        due_ids = [cid.decode() if isinstance(cid, bytes) else str(cid) for cid in due_ids_raw]

        # 2. IMMEDIATE ATOMIC POP
        # Remove from ZSET before processing to prevent head-of-line blocking or double-firing.
        await redis_client.zrem(SCHEDULER_KEY, *due_ids)

        async with SessionLocal() as session:
            for campaign_id_str in due_ids:
                try:
                    campaign_id = int(campaign_id_str)
                    # Fetch campaign with its organization
                    result = await session.execute(
                        select(Campaign).filter(Campaign.id == campaign_id)
                    )
                    campaign = result.scalar_one_or_none()

                    if not campaign:
                        logger.warning(f"Campaign {campaign_id} found in ZSET but missing in DB. Removing.")
                        continue

                    organization = await session.get(Organization, campaign.org_id)
                    
                    # 3. Validation & Dispatch
                    is_active = (
                        campaign.status == CampaignStatus.ACTIVE and 
                        organization and organization.is_active
                    )

                    if is_active:
                        logger.info(f"Dispatching campaign {campaign_id} to scraper queue.")
                        # Circular import safe dispatch
                        celery_app.send_task("tasks.workers.scraper_task", args=[campaign_id])
                    else:
                        logger.info(f"Campaign {campaign_id} skipped (Status: {campaign.status}, Org Active: {getattr(organization, 'is_active', False)})")

                    # 4. Reschedule (Always re-queue if exists in DB to maintain loop)
                    # Poll frequency is in minutes
                    next_poll = now + (campaign.poll_frequency_minutes * 60)
                    await redis_client.zadd(SCHEDULER_KEY, {str(campaign_id): next_poll})

                except Exception as e:
                    logger.error(f"Error processing campaign {campaign_id_str} in scheduler: {str(e)}")
                    # Defensive re-schedule to prevent losing the campaign in the ether
                    await redis_client.zadd(SCHEDULER_KEY, {campaign_id_str: now + 300}) # Retry in 5 mins

        await session.commit()

    asyncio.run(_tick())

async def enqueue_campaign(campaign_id: int, poll_frequency_minutes: int):
    """Manually add or reset a campaign in the scheduler."""
    next_poll = time.time() + (poll_frequency_minutes * 60)
    await redis_client.zadd(SCHEDULER_KEY, {str(campaign_id): next_poll})

async def remove_campaign(campaign_id: int):
    """Remove a campaign from the scheduler."""
    await redis_client.zrem(SCHEDULER_KEY, str(campaign_id))


@celery_app.task(name="tasks.scheduler.purge_old_webhook_events", bind=True, queue="maintenance")
def purge_old_webhook_events(self):
    """
    Maintenance task: Purges idempotency rows older than 30 days.
    TRD Section 12 implementation.
    """
    async def _purge():
        logger.info("Running purge_old_webhook_events task")
        expiry_threshold = datetime.now(timezone.utc) - timedelta(days=30)
        
        from sqlalchemy import delete
        async with SessionLocal() as db:
            stmt = delete(ProcessedWebhookEvent).where(
                ProcessedWebhookEvent.processed_at < expiry_threshold
            )
            result = await db.execute(stmt)
            await db.commit()
            
            logger.info(f"Purged {result.rowcount} expired webhook idempotency rows.")

    asyncio.run(_purge())

