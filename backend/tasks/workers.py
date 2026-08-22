import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update

from backend.celery_app import celery_app
from backend.database import build_session_factory
from backend.models import DraftReply, Campaign, CampaignStatus, DraftStatus
from backend.utils.celery_async import run_async

logger = logging.getLogger(__name__)


@celery_app.task(name="backend.tasks.workers.scraper_task", bind=True, max_retries=3, queue="scraper")
def scraper_task(self, campaign_id: int):
    """
    Scraper task: fetches source-platform posts and dispatches langgen.

    Platform-specific fetching (Reddit/LinkedIn/Twitter) is implemented via
    Apify actors in a later milestone (see org_apify_tokens / the Apify
    ingestion router). This task is a structural placeholder until that
    integration lands.
    """
    async def _run():
        logger.info(f"scraper_task invoked for campaign {campaign_id} (Apify integration pending)")
        engine, session_local = build_session_factory()
        try:
            async with session_local() as db:
                campaign = await db.get(Campaign, campaign_id)
                if not campaign or campaign.status != CampaignStatus.ACTIVE:
                    logger.warning(f"Campaign {campaign_id} not found or inactive.")
                    return
                logger.info(
                    f"Campaign {campaign_id} ({campaign.platform}) is due for polling; "
                    "deferring to Apify-backed scraper (not yet implemented)."
                )
        finally:
            await engine.dispose()

    run_async(_run)


@celery_app.task(name="backend.tasks.workers.langgen_task", bind=True, max_retries=3, queue="langgen")
def langgen_task(self, state: dict):
    """LangGen task: runs the LangGraph triage/generation nodes and persists the result."""
    async def _run():
        from backend.agent.graph import app as agent_app

        logger.info(f"Running langgen_task for campaign {state['campaign_id']}")

        engine, session_local = build_session_factory()
        try:
            async with session_local() as db:
                # The caller may not always have a real org_id on hand (e.g.
                # a hand-built state dict) -- fall back to the campaign's own
                # org_id so draft persistence never gets a null org_id.
                org_id = state.get("org_id")
                if not org_id:
                    campaign = await db.get(Campaign, state["campaign_id"])
                    org_id = campaign.org_id if campaign else None
                state_with_org = {**state, "org_id": org_id}

                final_state = await agent_app.ainvoke(state_with_org)

                draft = DraftReply(
                    org_id=final_state.get("org_id") or org_id,
                    campaign_id=final_state["campaign_id"],
                    platform=final_state["platform"],
                    post_id=final_state["post_id"],
                    url=final_state.get("url"),
                    original_content=final_state.get("original_content"),
                    ai_draft_text=final_state.get("ai_draft_text"),
                    confidence=final_state.get("confidence"),
                    triage_reasoning=final_state.get("triage_reasoning"),
                    signal_tier=final_state.get("signal_tier"),
                    status=final_state["final_status"],
                    prompt_template_version=final_state.get("prompt_template_version"),
                    response_token_count=final_state.get("response_token_count", 0),
                )
                db.add(draft)
                await db.commit()
                await db.refresh(draft)

                logger.info(f"Persisted DraftReply {draft.id} with status {draft.status}")
        finally:
            await engine.dispose()

    run_async(_run)


@celery_app.task(name="backend.tasks.workers.clear_expired_locks", bind=True, queue="maintenance")
def clear_expired_locks(self):
    """Maintenance task: clears draft locks older than 15 minutes."""
    async def _clear():
        logger.info("Running clear_expired_locks maintenance task")
        now = datetime.now(timezone.utc)

        engine, session_local = build_session_factory()
        try:
            async with session_local() as db:
                expiry_threshold = now - timedelta(minutes=15)

                stmt = (
                    update(DraftReply)
                    .where(
                        DraftReply.locked_at.is_not(None),
                        DraftReply.locked_at < expiry_threshold,
                    )
                    .values(locked_by_user_id=None, locked_at=None)
                )

                result = await db.execute(stmt)
                await db.commit()

                rows_cleared = result.rowcount
                if rows_cleared > 0:
                    logger.info(f"Cleared {rows_cleared} expired draft locks.")
                else:
                    logger.debug("No expired draft locks to clear.")
        finally:
            await engine.dispose()

    run_async(_clear)


@celery_app.task(name="backend.tasks.workers.poll_engagement_outcomes", bind=True, queue="maintenance")
def poll_engagement_outcomes(self):
    """
    Maintenance task: polls posted drafts for engagement outcomes (reactions,
    replies, reposts) at fixed intervals after posting.

    Logged no-op stub for M0 — real implementation (platform API polling +
    engagement_outcomes writes) lands in a later wave.
    """
    logger.info("poll_engagement_outcomes tick (stub — real implementation pending)")
