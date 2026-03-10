import asyncio
import logging
import os
import time
import redis.asyncio as redis
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from sqlalchemy import select, update
from celery_app import celery_app

from backend.database import SessionLocal
from backend.models import (
    DraftReply, Campaign, RedditAccount, AuditLog, 
    DraftStatus, CampaignStatus
)
from backend.agent.graph import app
from backend.utils.audit import write_audit_log
from backend.utils.encryption import decrypt
from backend.utils.praw_token import get_praw_token

logger = logging.getLogger(__name__)

# Redis Client for Lock and Rate Limiting (Async as per User Fix)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL)

async def _get_account_rate_limit(account_id: int) -> bool:
    """
    Enforces 2-second inter-post delay using Redis Sorted Set (Token Bucket).
    Returns True if allowed, False if busy.
    """
    now = time.time()
    key = f"praw:last_post:{account_id}"
    
    # Remove entries older than 2 seconds (Token Bucket approach via ZSET)
    await redis_client.zremrangebyscore(key, "-inf", now - 2.0)
    
    # Check if any entry remains within the last 2 seconds
    count = await redis_client.zcard(key)
    if count > 0:
        return False
        
    # Add current timestamp to reserve slot
    await redis_client.zadd(key, {str(now): now})
    await redis_client.expire(key, 10) # Cleanup safety
    return True

@celery_app.task(name="tasks.workers.scraper_task", bind=True, max_retries=3, queue="scraper")
def scraper_task(self, campaign_id: int):
    """
    Scraper task: Fetches Reddit posts and dispatches LangGen.
    Executes Node 1 & 2 of the pipeline logic.
    """
    from backend.agent.nodes.scraper import keyword_matcher, reddit_post_fetch
    import praw # Import inside task to avoid top-level overhead
    
    async def _run():
        logger.info(f"Running scraper_task for campaign {campaign_id}")
        
        async with SessionLocal() as db:
            # 1. Fetch Campaign and active Reddit Account
            campaign = await db.get(Campaign, campaign_id)
            if not campaign or campaign.status != CampaignStatus.ACTIVE:
                logger.warning(f"Campaign {campaign_id} not found or inactive.")
                return

            result = await db.execute(
                select(RedditAccount).where(
                    RedditAccount.org_id == campaign.org_id,
                    RedditAccount.is_active == True,
                    RedditAccount.deleted_at == None
                ).limit(1)
            )
            account = result.scalar_one_or_none()
            if not account:
                logger.error(f"No active Reddit account for org {campaign.org_id}")
                return

            # 2. Get Access Token (Async Step 3/4)
            token = await get_praw_token(account.id, account, redis_client)
            
            # 3. Initialize PRAW (Read-only/OAuth)
            reddit = praw.Reddit(
                client_id=account.client_id,
                client_secret=decrypt(account.encrypted_secret, version=account.encrypted_with_key_version),
                access_token=token,
                user_agent="SentinelDevRelAgent/1.0"
            )

            # 4. Fetch Top N posts from subreddit
            subreddit = reddit.subreddit(campaign.subreddit_name)
            # Use post_fetch_limit (or default to 10 if not set)
            limit = getattr(campaign, 'post_fetch_limit', 10)
            
            new_posts_found = 0
            
            def _fetch_submissions():
                return list(subreddit.new(limit=limit))
                
            submissions = await asyncio.to_thread(_fetch_submissions)
            
            for submission in submissions:
                post_id = submission.id
                
                # 5. Idempotency Check (TRD 4.5)
                # Check if we already have a draft for this post in this campaign
                stmt = select(DraftReply).where(
                    DraftReply.campaign_id == campaign_id,
                    DraftReply.reddit_post_id == post_id
                )
                existing = await db.execute(stmt)
                if existing.scalar_one_or_none():
                    continue

                # 6. Basic Triage (Execute Node 1 & 2 logic)
                # We reuse the node functions by passing the partial state
                initial_state = {
                    "campaign_id": campaign_id,
                    "reddit_post_id": post_id,
                    "post_url": f"https://reddit.com{submission.permalink}",
                    "original_text": f"Title: {submission.title}\n\n{submission.selftext}",
                    "matched_keywords": [],
                    "pre_filter_pass": False,
                    "confidence_score": 0.0,
                    "triage_reasoning": "",
                    "truncation_applied": False,
                    "truncation_details": {},
                    "ai_draft_text": "",
                    "model_payload_token_count": 0,
                    "final_status": DraftStatus.PENDING
                }
                
                # Check for keyword matches immediately (Node 2 logic)
                state = await keyword_matcher(initial_state)
                
                if state["pre_filter_pass"]:
                    logger.info(f"Keyword match for campaign {campaign_id}, post {post_id}. Handoff to langgen.")
                    # Dispatch langgen_task
                    celery_app.send_task("tasks.workers.langgen_task", args=[state])
                    new_posts_found += 1
                else:
                    logger.debug(f"Post {post_id} skipped (no keyword match).")

            logger.info(f"Scraper finished for campaign {campaign_id}. Dispatched {new_posts_found} tasks.")

    asyncio.run(_run())

@celery_app.task(name="tasks.workers.langgen_task", bind=True, max_retries=3, queue="langgen")
def langgen_task(self, state: Dict[str, Any]):
    """
    LangGen task: Runs Nodes 3-6 of the LangGraph pipeline sequentially.
    """
    async def _run():
        logger.info(f"Running langgen_task for campaign {state['campaign_id']}")
        
        # Invoke the compiled LangGraph application.
        # Nodes 3-6 execute in-memory within this task as per TRD 4.3.
        final_state = await app.ainvoke(state)
        
        # Persist the workflow result to DraftReply
        async with SessionLocal() as db:
            draft = DraftReply(
                campaign_id=final_state["campaign_id"],
                reddit_post_id=final_state["reddit_post_id"],
                reddit_post_url=final_state["post_url"],
                original_text=final_state["original_text"],
                ai_draft_text=final_state["ai_draft_text"],
                confidence_score=final_state["confidence_score"],
                status=final_state["final_status"],
                truncation_applied=final_state.get("truncation_applied", False),
                truncation_details=final_state.get("truncation_details", {}),
                model_payload_token_count=final_state.get("model_payload_token_count", 0)
            )
            db.add(draft)
            await db.commit()
            await db.refresh(draft)
            
            logger.info(f"Persisted DraftReply {draft.id} with status {draft.status}")
            
            # Auto-Pilot handoff: Dispatch to publish queue if criteria met
            if draft.status == DraftStatus.PUBLISHED:
                celery_app.send_task("tasks.workers.praw_publish_task", args=[draft.id])

    asyncio.run(_run())

@celery_app.task(name="tasks.workers.praw_publish_task", bind=True, max_retries=5, queue="praw_publish")
def praw_publish_task(self, draft_id: int):
    """
    PRAW publish task: Publishes reply to Reddit with idempotency & rate limits.
    """
    async def _publish():
        logger.info(f"PRAW publish check for draft {draft_id}")
        
        # 1. Redis Idempotency Lock (TRD Section 6)
        lock_key = f"praw_publish:{draft_id}"
        if not await redis_client.set(lock_key, "locked", nx=True, px=300000): # 5 min TTL
            logger.warning(f"Publish operation for draft {draft_id} is already in progress.")
            return

        try:
            async with SessionLocal() as db:
                # Load draft and check status
                draft = await db.get(DraftReply, draft_id)
                if not draft or draft.status == DraftStatus.PUBLISHED:
                    logger.info(f"Draft {draft_id} is already published or missing.")
                    return

                campaign = await db.get(Campaign, draft.campaign_id)
                
                # Retrieve active Reddit account
                result = await db.execute(
                    select(RedditAccount).where(
                        RedditAccount.org_id == campaign.org_id,
                        RedditAccount.is_active == True
                    ).limit(1)
                )
                account = result.scalar_one_or_none()
                if not account:
                    raise ValueError(f"No active Reddit account found for org {campaign.org_id}")

                # 2. Redis Sorted Set Rate Limiter (2-second inter-post delay)
                if not await _get_account_rate_limit(account.id):
                    logger.info(f"Account {account.username} rate limit active. Re-queuing...")
                    self.retry(countdown=2)
                    return

                # 3. Publish Execution
                import praw
                token = await get_praw_token(account.id, account, redis_client)
                logger.info(f"Publishing reply via account {account.username}")
                
                reddit = praw.Reddit(
                    client_id=account.client_id,
                    client_secret=decrypt(account.encrypted_secret, version=account.encrypted_with_key_version),
                    access_token=token,
                    user_agent="SentinelDevRelAgent/1.0"
                )

                # Fetch submission and post reply
                submission = reddit.submission(id=draft.reddit_post_id)
                reply = submission.reply(draft.ai_draft_text)
                published_url = f"https://reddit.com{reply.permalink}"
                
                # 4. Successful State Transition
                draft.status = DraftStatus.PUBLISHED
                draft.published_at = datetime.now(timezone.utc)
                draft.live_reddit_url = published_url
                draft.published_by_account_id = account.id
                
                # Audit Log: DRAFT_PUBLISHED
                await write_audit_log(
                    db, 
                    org_id=campaign.org_id,
                    action="DRAFT_PUBLISHED",
                    details={"draft_id": draft_id, "account": account.username, "url": published_url, "comment_id": reply.id}
                )
                
                await db.commit()
                logger.info(f"Published Draft {draft_id} successfully as {reply.id}.")

        except Exception as e:
            logger.error(f"Publish failure for draft {draft_id}: {str(e)}")
            # Defensive Audit Log & Status Update
            async with SessionLocal() as db_fail:
                d = await db_fail.get(DraftReply, draft_id)
                if d:
                    d.status = DraftStatus.FAILED
                    d.failed_reason = str(e)
                    
                    c = await db_fail.get(Campaign, d.campaign_id)
                    await write_audit_log(
                        db_fail,
                        org_id=c.org_id,
                        action="DRAFT_PUBLISHED_FAILED",
                        details={"draft_id": draft_id, "error": str(e)}
                    )
                    await db_fail.commit()
            raise e
        # Idempotency lock remains for TTL to prevent double-posting on rapid retries

    asyncio.run(_publish())

@celery_app.task(name="tasks.workers.praw_delete", bind=True, max_retries=10, queue="praw_publish")
def praw_delete(self, draft_id: int):
    """
    PRAW delete task (Kill Switch): Share same queue and rate limits as publishing.
    """
    async def _delete():
        logger.info(f"Kill Switch: Deleting draft {draft_id}")
        
        async with SessionLocal() as db:
            draft = await db.get(DraftReply, draft_id)
            if not draft or not draft.live_reddit_url:
                logger.warning(f"Draft {draft_id} is not in a deletable live state.")
                return

            campaign = await db.get(Campaign, draft.campaign_id)
            account = await db.get(RedditAccount, draft.published_by_account_id)
            
            if not account:
                logger.error(f"Publishing account context missing for draft {draft_id}")
                return

            # Rate Limit Sync
            if not await _get_account_rate_limit(account.id):
                logger.info(f"Delete delayed by account rate limit. Re-queuing...")
                self.retry(countdown=2)
                return

            # Actual PRAW Comment deletion
            import praw
            token = await get_praw_token(account.id, account, redis_client)
            reddit = praw.Reddit(
                client_id=account.client_id,
                client_secret=decrypt(account.encrypted_secret, version=account.encrypted_with_key_version),
                access_token=token,
                user_agent="SentinelDevRelAgent/1.0"
            )
            
            comment = reddit.comment(url=draft.live_reddit_url)
            comment.delete()
            logger.info(f"Deleted comment {draft.live_reddit_url} from account {account.username}")
            
            # Transition status
            draft.status = DraftStatus.DELETED_BY_KILLSWITCH
            
            # Audit Log: KILLSWITCH_POST_DELETED
            await write_audit_log(
                db,
                org_id=campaign.org_id,
                action="KILLSWITCH_POST_DELETED",
                details={"draft_id": draft_id, "account": account.username, "url": draft.live_reddit_url}
            )
            
            await db.commit()
            logger.info(f"Kill Switch success for draft {draft_id}")

    asyncio.run(_delete())
@celery_app.task(name="tasks.workers.clear_expired_locks", bind=True, queue="maintenance")
def clear_expired_locks(self):
    """
    Maintenance task: Clears draft locks older than 15 minutes.
    Adheres to TRD Section 5.6.
    """
    async def _clear():
        logger.info("Running clear_expired_locks maintenance task")
        now = datetime.now(timezone.utc)
        
        async with SessionLocal() as db:
            # 15 minutes = 900 seconds
            expiry_threshold = now - timedelta(minutes=15)
            
            stmt = update(DraftReply).where(
                DraftReply.locked_at != None,
                DraftReply.locked_at < expiry_threshold
            ).values(
                locked_by_user_id=None,
                locked_at=None
            )
            
            result = await db.execute(stmt)
            await db.commit()
            
            rows_cleared = result.rowcount
            if rows_cleared > 0:
                logger.info(f"Cleared {rows_cleared} expired draft locks.")
            else:
                logger.debug("No expired draft locks to clear.")

    asyncio.run(_clear())
