import logging
import time
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update

from backend.celery_app import celery_app
from backend.database import build_session_factory
from backend.models import DraftReply
from backend.utils.celery_async import run_async, new_redis_client

logger = logging.getLogger(__name__)


@celery_app.task(name="backend.tasks.workers.scraper_task", bind=True, max_retries=3, queue="scraper")
def scraper_task(self, campaign_id: int):
    """
    Reserved for future use. As of M2, ``langgen_task`` runs the whole reply
    pipeline (ingest through persist_gate) as one Celery task/one LangGraph
    run, so ``scheduler_tick`` no longer dispatches here -- see PRD V7 §5.3.
    The ``scraper`` queue stays declared in backend/celery_app.py for
    whatever eventually wants a separate ingest-only task (e.g. a shared
    fan-out ingest step for the Analyst pipeline, M3).
    """
    logger.info(
        "scraper_task invoked for campaign %s -- no-op as of M2; the reply "
        "pipeline's ingest node handles ingestion directly (see backend.pipeline.nodes.ingest_node)",
        campaign_id,
    )


@celery_app.task(name="backend.tasks.workers.langgen_task", bind=True, max_retries=3, queue="langgen")
def langgen_task(self, campaign_id: int, scheduled_ts: float | None = None):
    """
    Runs graph #1 (PRD V7 §5.3) end to end for one campaign poll:

        ingest -> prefilter -> scout -> token_budget -> strategist -> finalize -> persist_gate

    ``scheduled_ts`` is the scheduler tick's timestamp; together with
    ``campaign_id`` it forms the LangGraph checkpoint thread_id
    (``backend.pipeline.graph.thread_id_for``). A Celery retry of this exact
    task instance reuses the same ``(campaign_id, scheduled_ts)`` args, so it
    resumes from the last completed node instead of re-ingesting (and
    re-billing Apify) -- see ``backend.pipeline.graph.run_pipeline``.
    """
    if scheduled_ts is None:
        scheduled_ts = time.time()

    async def _run():
        from backend.pipeline.graph import run_pipeline

        engine, session_local = build_session_factory()
        redis_client = new_redis_client()
        try:
            final_state = await run_pipeline(campaign_id, scheduled_ts, session_local, redis_client)
            logger.info(
                "langgen_task campaign=%s scheduled_ts=%s persisted=%d terminal_reason=%s errors=%s",
                campaign_id,
                scheduled_ts,
                len(final_state.get("persisted_draft_ids", []) or []),
                final_state.get("terminal_reason"),
                final_state.get("errors"),
            )
        finally:
            await redis_client.aclose()
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
    Maintenance task (PRD V7 §5.7): for POSTED drafts with a live_url, fetch
    +24h/+72h metrics and persist EngagementOutcome rows. Reddit-only for
    M2 (free ``.json`` endpoint, no auth); LinkedIn/Twitter are logged and
    skipped -- see backend.pipeline.outcomes for the TODO.
    """
    async def _poll():
        from backend.pipeline.outcomes import poll_engagement_outcomes as run_outcomes_poll

        engine, session_local = build_session_factory()
        try:
            stats = await run_outcomes_poll(session_local)
            logger.info("poll_engagement_outcomes stats=%s", stats)
        finally:
            await engine.dispose()

    run_async(_poll)
