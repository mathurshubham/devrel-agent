import logging
import time
from datetime import date, datetime, timezone, timedelta

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


@celery_app.task(
    name="backend.tasks.workers.analyst_task",
    bind=True,
    max_retries=3,
    queue="langgen",
    acks_late=True,
    reject_on_worker_lost=True,
)
def analyst_task(self, org_id: int, run_id: int, week_of: str):
    """
    Runs graph #2 (PRD V7 §5.6) end to end for one org's weekly Analyst run:

        ingest -> triage -> cluster -> stance -> quotes -> aggregate -> render_brief

    ``week_of`` (ISO date, the Monday of the analysis week) is fixed by the
    caller -- the weekly beat tick or the on-demand trigger endpoint -- and
    passed explicitly rather than recomputed here, so a Celery retry of this
    exact task reuses the same ``(org_id, week_of)`` -> same checkpoint
    thread_id (``backend.pipeline.analyst_graph.thread_id_for``) -> resumes
    instead of re-ingesting or re-running LLM steps already completed.

    ``acks_late``/``reject_on_worker_lost``: same crash-safety rationale as
    ``langgen_task`` above -- a worker killed mid-run gets this task
    redelivered with identical args, landing back in the checkpoint's
    resume-with-``None`` branch.
    """
    async def _run():
        from backend.pipeline.analyst_graph import run_analyst_pipeline

        engine, session_local = build_session_factory()
        redis_client = new_redis_client()
        try:
            final_state = await run_analyst_pipeline(
                org_id, date.fromisoformat(week_of), run_id, session_local, redis_client
            )
            logger.info(
                "analyst_task org=%s run=%s week_of=%s brief_id=%s terminal_reason=%s errors=%s",
                org_id, run_id, week_of,
                final_state.get("brief_id"),
                final_state.get("terminal_reason"),
                final_state.get("errors"),
            )
        except Exception:
            logger.exception("analyst_task org=%s run=%s week_of=%s failed", org_id, run_id, week_of)
            async with session_local() as db:
                from backend.models import AnalystRun

                run = await db.get(AnalystRun, run_id)
                if run and run.status not in ("COMPLETED", "FAILED"):
                    run.status = "FAILED"
                    run.finished_at = datetime.now(timezone.utc)
                    await db.commit()
            raise
        finally:
            await redis_client.aclose()
            await engine.dispose()

    run_async(_run)


@celery_app.task(name="backend.tasks.workers.analyst_weekly_tick", bind=True, queue="maintenance")
def analyst_weekly_tick(self):
    """
    Celery Beat task (Mon 06:00 UTC, PRD V7 §5.6): dispatches one
    ``analyst_task`` per *active* org with ``OrgSettings.analyst_enabled``
    set, unless that org already has a non-stale non-terminal run for the
    current week (avoids double-dispatch if beat fires more than once,
    e.g. after a restart).
    """
    async def _tick():
        from backend.models import AnalystRun, Organization, OrgSettings
        from backend.pipeline.analyst_graph import current_week_of, non_stale_non_terminal_filter

        engine, session_local = build_session_factory()
        try:
            week_of = current_week_of()
            async with session_local() as db:
                # Deactivated orgs must not get weekly Analyst runs dispatched
                # -- same guard scheduler_tick applies to reply-pipeline
                # campaigns (backend.tasks.scheduler.scheduler_tick).
                org_ids = (
                    (
                        await db.execute(
                            select(OrgSettings.org_id)
                            .join(Organization, Organization.id == OrgSettings.org_id)
                            .where(
                                OrgSettings.analyst_enabled.is_(True),
                                Organization.is_active.is_(True),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

                dispatched = 0
                for org_id in org_ids:
                    try:
                        existing = (
                            await db.execute(
                                select(AnalystRun)
                                .where(AnalystRun.org_id == org_id, AnalystRun.week_of == week_of)
                                .where(non_stale_non_terminal_filter())
                                .order_by(AnalystRun.id.desc())
                                .limit(1)
                            )
                        ).scalars().first()
                        if existing:
                            continue

                        run = AnalystRun(
                            org_id=org_id, week_of=week_of, status="RUNNING",
                            started_at=datetime.now(timezone.utc),
                        )
                        db.add(run)
                        await db.flush()
                        # Commit this org's row BEFORE send_task -- the
                        # worker picking up analyst_task must never race an
                        # uncommitted AnalystRun row (and a per-org commit
                        # means one org's failure below can't roll back
                        # another org's already-dispatched run).
                        await db.commit()

                        celery_app.send_task(
                            "backend.tasks.workers.analyst_task",
                            args=[org_id, run.id, week_of.isoformat()],
                        )
                        dispatched += 1
                    except Exception:
                        # One org's dispatch failure (a bad row, a transient
                        # DB error) must not starve every other org in this
                        # tick -- roll back just this iteration and continue.
                        logger.exception("analyst_weekly_tick: dispatch failed for org=%s", org_id)
                        await db.rollback()
                        continue

                logger.info("analyst_weekly_tick: dispatched %d org(s) for week_of=%s", dispatched, week_of)
        finally:
            await engine.dispose()

    run_async(_tick)


@celery_app.task(name="backend.tasks.workers.reap_stale_analyst_runs", bind=True, queue="maintenance")
def reap_stale_analyst_runs(self):
    """
    Maintenance task: marks RUNNING ``AnalystRun`` rows older than
    ``backend.pipeline.analyst_graph.STALE_RUN_AFTER_HOURS`` as FAILED
    (reason=stale).

    Without this, a run whose worker crashed (or whose checkpoint thread
    otherwise never reaches a terminal node) leaves its ``AnalystRun`` row
    RUNNING forever -- and since the on-demand trigger's 409 check and this
    module's own weekly-tick dispatch guard are org-scoped (not run-scoped),
    a single wedged row would otherwise permanently block every future run
    for that org.
    """
    async def _reap():
        from backend.models import AnalystRun, SystemLog, now_utc
        from backend.pipeline.analyst_graph import STALE_RUN_AFTER_HOURS, stale_cutoff

        engine, session_local = build_session_factory()
        try:
            cutoff = stale_cutoff()
            async with session_local() as db:
                stale_runs = (
                    await db.execute(
                        select(AnalystRun).where(
                            AnalystRun.status == "RUNNING", AnalystRun.started_at < cutoff
                        )
                    )
                ).scalars().all()

                for run in stale_runs:
                    run.status = "FAILED"
                    run.finished_at = now_utc()
                    db.add(
                        SystemLog(
                            org_id=run.org_id,
                            level="WARNING",
                            module="tasks.reap_stale_analyst_runs",
                            message=(
                                f"Analyst run {run.id} (week_of={run.week_of.isoformat()}) marked "
                                f"FAILED reason=stale (started_at="
                                f"{run.started_at.isoformat() if run.started_at else None}, "
                                f"threshold={STALE_RUN_AFTER_HOURS}h)"
                            ),
                        )
                    )

                await db.commit()
                if stale_runs:
                    logger.warning(
                        "reap_stale_analyst_runs: marked %d run(s) FAILED (reason=stale)", len(stale_runs)
                    )
        finally:
            await engine.dispose()

    run_async(_reap)


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
