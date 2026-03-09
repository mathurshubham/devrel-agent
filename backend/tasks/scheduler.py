import time
import redis
import os
from celery_app import celery_app
from sqlalchemy.orm import Session
from database import engine
from models import Campaign, CampaignStatus
import logging

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.from_url(REDIS_URL)

SCHEDULER_KEY = "campaign:scheduler"

@celery_app.task(name="tasks.scheduler.scheduler_tick")
def scheduler_tick():
    """
    Celery Beat task that runs every 60 seconds.
    Queries Redis ZSET for due campaigns and dispatches them to the scraper queue.
    """
    now = time.time()
    # Query due campaigns (score <= now)
    due_ids = r.zrangebyscore(SCHEDULER_KEY, 0, now)
    
    if not due_ids:
        logger.info("No campaigns due for polling.")
        return

    # Convert bytes to strings
    due_ids_str = [cid.decode() if isinstance(cid, bytes) else str(cid) for cid in due_ids]
    
    # Atomically remove before dispatch (no double-fire)
    # TRD 4.10: redis.zrem('campaign:scheduler', *due_ids)
    r.zrem(SCHEDULER_KEY, *due_ids)
    
    with Session(engine) as session:
        for campaign_id_str in due_ids_str:
            try:
                campaign_id = int(campaign_id_str)
                campaign = session.get(Campaign, campaign_id)
                
                if campaign and campaign.status == CampaignStatus.ACTIVE:
                    # Check if the organization is active before dispatching
                    if campaign.organization and campaign.organization.is_active:
                        logger.info(f"Dispatching campaign {campaign_id} to scraper queue.")
                        # Apply async to scraper queue
                        from tasks.workers import scraper_task
                        scraper_task.apply_async(args=[campaign_id], queue="scraper")
                    else:
                        logger.warning(f"Organization for campaign {campaign_id} is inactive. Skipping.")
                    
                    # Schedule next poll
                    next_poll = now + (campaign.poll_frequency_minutes * 60)
                    r.zadd(SCHEDULER_KEY, {campaign_id_str: next_poll})
                else:
                    logger.info(f"Campaign {campaign_id} is not active. Skipping re-scheduling.")
                    
            except Exception as e:
                logger.error(f"Error processing campaign {campaign_id_str}: {str(e)}")
                # Potentially re-schedule if it's a transient DB error? 
                # For now, let's keep it simple as per TRD.

def enqueue_campaign(campaign_id: int, poll_frequency_minutes: int):
    """Utility to manually enqueue or re-activate a campaign."""
    next_poll = time.time() + (poll_frequency_minutes * 60)
    r.zadd(SCHEDULER_KEY, {str(campaign_id): next_poll})

def remove_campaign(campaign_id: int):
    """Utility to remove a campaign from the scheduler."""
    r.zrem(SCHEDULER_KEY, str(campaign_id))
