import asyncio
import logging
import os
import time
import redis.asyncio as redis
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, delete

from backend.celery_app import celery_app
from backend.database import SessionLocal
from backend.models import Campaign, CampaignStatus, Organization, ProcessedWebhookEvent

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL)

SCHEDULER_KEY = "campaign:scheduler"


@celery_app.task(name="backend.tasks.scheduler.scheduler_tick", bind=True, queue="maintenance")
def scheduler_tick(self):
    """
    Celery Beat task: drift-free polling using a Redis ZSET priority queue.
    """
    async def _tick():
        now = time.time()
        logger.info(f"Running scheduler_tick at {now}")

        due_ids_raw = await redis_client.zrangebyscore(SCHEDULER_KEY, 0, now)
        if not due_ids_raw:
            logger.info("No campaigns due for polling.")
            return

        due_ids = [cid.decode() if isinstance(cid, bytes) else str(cid) for cid in due_ids_raw]

        # Atomic pop before processing, to prevent double-firing.
        await redis_client.zrem(SCHEDULER_KEY, *due_ids)

        async with SessionLocal() as session:
            for campaign_id_str in due_ids:
                try:
                    campaign_id = int(campaign_id_str)
                    result = await session.execute(
                        select(Campaign).filter(Campaign.id == campaign_id)
                    )
                    campaign = result.scalar_one_or_none()

                    if not campaign:
                        logger.warning(f"Campaign {campaign_id} found in ZSET but missing in DB. Removing.")
                        continue

                    organization = await session.get(Organization, campaign.org_id)

                    is_active = (
                        campaign.status == CampaignStatus.ACTIVE
                        and organization is not None
                        and organization.is_active
                    )

                    if is_active:
                        logger.info(f"Dispatching campaign {campaign_id} to scraper queue.")
                        celery_app.send_task("backend.tasks.workers.scraper_task", args=[campaign_id])
                    else:
                        logger.info(
                            f"Campaign {campaign_id} skipped "
                            f"(Status: {campaign.status}, Org Active: {getattr(organization, 'is_active', False)})"
                        )

                    # Reschedule to keep the loop alive.
                    next_poll = now + (campaign.poll_frequency_minutes * 60)
                    await redis_client.zadd(SCHEDULER_KEY, {str(campaign_id): next_poll})

                except Exception as e:
                    logger.error(f"Error processing campaign {campaign_id_str} in scheduler: {str(e)}")
                    await redis_client.zadd(SCHEDULER_KEY, {campaign_id_str: now + 300})

            # FIX: commit was previously issued outside the `async with SessionLocal()`
            # block, after the session had already closed — the reschedule state
            # written above (org lookups notwithstanding) never persisted.
            await session.commit()

    asyncio.run(_tick())


async def enqueue_campaign(campaign_id: int, poll_frequency_minutes: int):
    """Add or reset a campaign in the scheduler ZSET. Call on campaign create/resume."""
    next_poll = time.time() + (poll_frequency_minutes * 60)
    await redis_client.zadd(SCHEDULER_KEY, {str(campaign_id): next_poll})


async def remove_campaign(campaign_id: int):
    """Remove a campaign from the scheduler ZSET. Call on pause/archive/delete."""
    await redis_client.zrem(SCHEDULER_KEY, str(campaign_id))


@celery_app.task(name="backend.tasks.scheduler.purge_old_webhook_events", bind=True, queue="maintenance")
def purge_old_webhook_events(self):
    """Maintenance task: purges idempotency rows older than 30 days."""
    async def _purge():
        logger.info("Running purge_old_webhook_events task")
        expiry_threshold = datetime.now(timezone.utc) - timedelta(days=30)

        async with SessionLocal() as db:
            stmt = delete(ProcessedWebhookEvent).where(
                ProcessedWebhookEvent.processed_at < expiry_threshold
            )
            result = await db.execute(stmt)
            await db.commit()

            logger.info(f"Purged {result.rowcount} expired webhook idempotency rows.")

    asyncio.run(_purge())
