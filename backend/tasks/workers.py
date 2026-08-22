import logging
import time
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update

from backend.celery_app import celery_app
from backend.database import build_session_factory
from backend.models import DraftReply
from backend.utils.celery_async import run_async, new_redis_client

logger = logging.getLogger(__name__)


@celery_app.task(
    name="backend.tasks.workers.scraper_task",
    bind=True,
    max_retries=3,
    queue="scraper",
    acks_late=True,
    reject_on_worker_lost=True,
)
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


@celery_app.task(
    name="backend.tasks.workers.langgen_task",
    bind=True,
    max_retries=3,
    queue="langgen",
    acks_late=True,
    reject_on_worker_lost=True,
)
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

    ``acks_late=True`` + ``reject_on_worker_lost=True``: without these, the
    default is "ack on delivery" -- if the worker process is killed
    mid-run (OOM, deploy, ``SIGKILL``), Celery has already acked the
    message and it is gone for good, so the checkpoint resume path above
    can never actually be reached in production (nothing ever redelivers
    the task to trigger it). With them, a task whose worker dies mid-run
    is instead requeued and redelivered with the *same* args -- same
    ``campaign_id``/``scheduled_ts`` -> same thread_id -> the retry lands
    back in ``run_pipeline``'s resume-with-``None`` branch and continues
    from the last completed node. This is safe to redeliver even if the
    original attempt actually finished right as the worker died (the
    at-least-once redelivery race): every node's own DB write is
    idempotent (the ``PostedHistory``/``DraftReply`` dedup checks in
    ``prefilter_node``, the ``IntegrityError`` safety net in
    ``persist_gate_node``), and the checkpoint itself means a fully
    completed run has no un-run nodes left for the redelivered task to
    redo.
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


@celery_app.task(name="backend.tasks.workers.purge_old_checkpoints_task", bind=True, queue="maintenance")
def purge_old_checkpoints_task(self):
    """
    Maintenance task (daily): delete LangGraph checkpoint state older than
    7 days.

    ``langgraph-checkpoint-postgres`` never expires anything itself, so
    left alone the ``checkpoints``/``checkpoint_blobs``/``checkpoint_writes``
    tables grow unboundedly -- and each checkpoint blob is a full snapshot
    of pipeline state, including ingested post content, which would
    otherwise outlive the PRD's retention schedule for that data. See
    ``backend.pipeline.graph.purge_old_checkpoints`` for the actual
    thread-scoped delete.
    """
    async def _purge():
        from backend.pipeline.graph import purge_old_checkpoints

        logger.info("Running purge_old_checkpoints_task maintenance task")
        stats = await purge_old_checkpoints(retention_days=7)
        logger.info("purge_old_checkpoints_task stats=%s", stats)

    run_async(_purge)


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
