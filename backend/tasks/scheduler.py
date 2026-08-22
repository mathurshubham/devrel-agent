import logging
import os
import time
import redis.asyncio as redis
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, delete

from backend.celery_app import celery_app
from backend.database import build_session_factory
from backend.models import Campaign, CampaignStatus, Organization, ProcessedWebhookEvent
from backend.utils.celery_async import run_async, new_redis_client

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

SCHEDULER_KEY = "campaign:scheduler"


@celery_app.task(name="backend.tasks.scheduler.scheduler_tick", bind=True, queue="maintenance")
def scheduler_tick(self):
    """
    Celery Beat task: drift-free polling using a Redis ZSET priority queue.
    """
    async def _tick():
        redis_client = new_redis_client()
        engine, session_local = build_session_factory()
        try:
            now = time.time()
            logger.info(f"Running scheduler_tick at {now}")

            due_ids_raw = await redis_client.zrangebyscore(SCHEDULER_KEY, 0, now)
            if not due_ids_raw:
                logger.info("No campaigns due for polling.")
                return

            due_ids = [cid.decode() if isinstance(cid, bytes) else str(cid) for cid in due_ids_raw]

            # Pop the due members before processing, so a slow/crashed tick
            # can't cause the next tick to double-fire the same campaigns.
            await redis_client.zrem(SCHEDULER_KEY, *due_ids)

            async with session_local() as session:
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
                            # PRD V7 §5.3: the whole reply pipeline (ingest
                            # through persist_gate) runs as one LangGraph
                            # run inside a single langgen task -- there is
                            # no separate scraper hop to dispatch to.
                            # scheduled_ts becomes part of the pipeline's
                            # checkpoint thread_id (backend.pipeline.graph),
                            # so a Celery retry of this exact task resumes
                            # instead of re-ingesting.
                            logger.info(f"Dispatching campaign {campaign_id} to langgen queue.")
                            celery_app.send_task(
                                "backend.tasks.workers.langgen_task", args=[campaign_id, now]
                            )
                        else:
                            logger.info(
                                f"Campaign {campaign_id} skipped "
                                f"(Status: {campaign.status}, Org Active: {getattr(organization, 'is_active', False)})"
                            )

                        # Reschedule to keep the loop alive.
                        next_poll = now + (campaign.poll_frequency_minutes * 60)
                        await redis_client.zadd(SCHEDULER_KEY, {str(campaign_id): next_poll})

                    except Exception as e:
                        # One bad campaign (a DB error, a bad row) must not
                        # poison the session -- and therefore skip -- every
                        # remaining campaign in this tick. Roll back just
                        # this iteration's work and keep going.
                        logger.error(f"Error processing campaign {campaign_id_str} in scheduler: {str(e)}")
                        await session.rollback()
                        await redis_client.zadd(SCHEDULER_KEY, {campaign_id_str: now + 300})

                await session.commit()
        finally:
            await redis_client.aclose()
            await engine.dispose()

    run_async(_tick)


async def enqueue_campaign(campaign_id: int, poll_frequency_minutes: int):
    """Add or reset a campaign in the scheduler ZSET. Call on campaign create/resume."""
    redis_client = redis.from_url(REDIS_URL)
    try:
        next_poll = time.time() + (poll_frequency_minutes * 60)
        await redis_client.zadd(SCHEDULER_KEY, {str(campaign_id): next_poll})
    finally:
        await redis_client.aclose()


async def enqueue_campaign_now(campaign_id: int):
    """Add a campaign to the scheduler ZSET due immediately. Call on campaign create."""
    redis_client = redis.from_url(REDIS_URL)
    try:
        await redis_client.zadd(SCHEDULER_KEY, {str(campaign_id): time.time()})
    finally:
        await redis_client.aclose()


async def remove_campaign(campaign_id: int):
    """Remove a campaign from the scheduler ZSET. Call on pause/archive/delete."""
    redis_client = redis.from_url(REDIS_URL)
    try:
        await redis_client.zrem(SCHEDULER_KEY, str(campaign_id))
    finally:
        await redis_client.aclose()


@celery_app.task(name="backend.tasks.scheduler.purge_old_webhook_events", bind=True, queue="maintenance")
def purge_old_webhook_events(self):
    """Maintenance task: purges idempotency rows older than 30 days."""
    async def _purge():
        logger.info("Running purge_old_webhook_events task")
        expiry_threshold = datetime.now(timezone.utc) - timedelta(days=30)

        engine, session_local = build_session_factory()
        try:
            async with session_local() as db:
                stmt = delete(ProcessedWebhookEvent).where(
                    ProcessedWebhookEvent.processed_at < expiry_threshold
                )
                result = await db.execute(stmt)
                await db.commit()

                logger.info(f"Purged {result.rowcount} expired webhook idempotency rows.")
        finally:
            await engine.dispose()

    run_async(_purge)
