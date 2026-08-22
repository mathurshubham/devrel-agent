"""Graph #2 wiring (PRD V7 §5.6): a real ``StateGraph``, Postgres-checkpointed
exactly like graph #1 (``backend.pipeline.graph``) -- same
``langgraph-checkpoint-postgres`` tables, same resume semantics, different
``thread_id`` namespace so the two graphs' checkpoints never collide:

    ingest -> triage -> cluster -> stance -> quotes -> aggregate -> render_brief

``thread_id = f"analyst:{org_id}:{week_of}:{run_id}"``: every ``AnalystRun``
row gets its *own* checkpoint thread. A retried Celery task for the exact
same run (same ``run_id``) resumes from the last completed node instead of
re-ingesting (and re-billing Apify) or re-running LLM calls already done --
but a *second, distinct* run for the same ``(org_id, week_of)`` (a
re-trigger, a retry that raced a completed run, ...) never collides with an
earlier run's already-``END`` checkpoint. Before ``run_id`` was part of the
thread key, a second same-week run resumed the first run's finished
checkpoint, executed zero nodes, and returned the first run's state while
its own ``AnalystRun`` row stayed ``RUNNING`` forever -- see
``STALE_RUN_AFTER_HOURS``/``stale_cutoff`` below for the safety net that
recovers a row wedged that way regardless.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from langgraph.graph import END, StateGraph
from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from backend.models import AnalystRun
from backend.pipeline.analyst_nodes import (
    aggregate_node,
    cluster_node,
    ingest_node,
    quotes_node,
    render_brief_node,
    stance_node,
    triage_node,
)
from backend.pipeline.analyst_state import AnalystState, new_initial_analyst_state
from backend.pipeline.graph import _psycopg_conn_string

logger = logging.getLogger(__name__)

#: AnalystRun.status values that mean "still in flight" -- used by the
#: on-demand trigger endpoint's 409 check and the weekly beat task's
#: "don't double-dispatch this org" guard.
NON_TERMINAL_RUN_STATUSES = {"PENDING", "RUNNING"}

#: A RUNNING AnalystRun older than this is treated as wedged (crashed
#: worker, lost/never-progressed checkpoint) rather than genuinely in
#: flight -- see ``backend.tasks.workers.reap_stale_analyst_runs``, which
#: sweeps these to FAILED, and ``non_stale_non_terminal_filter`` below,
#: which keeps a wedged row from permanently blocking new runs for its
#: org/week in the meantime.
STALE_RUN_AFTER_HOURS = 2


def stale_cutoff(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)) - timedelta(hours=STALE_RUN_AFTER_HOURS)


def non_stale_non_terminal_filter(now: Optional[datetime] = None) -> ColumnElement:
    """SQLAlchemy filter: ``AnalystRun`` is non-terminal AND not a stale
    RUNNING row (RUNNING for longer than ``STALE_RUN_AFTER_HOURS`` with no
    reaper having reached it yet).

    Shared by the on-demand trigger's 409 check (``backend.api.analyst``)
    and the weekly beat's don't-double-dispatch guard
    (``backend.tasks.workers.analyst_weekly_tick``) so a wedged run can
    never permanently block a fresh run for that org/week.
    """
    cutoff = stale_cutoff(now)
    return and_(
        AnalystRun.status.in_(NON_TERMINAL_RUN_STATUSES),
        or_(AnalystRun.status != "RUNNING", AnalystRun.started_at >= cutoff),
    )


def _after_ingest(state: AnalystState) -> str:
    return END if state.get("terminal") else "triage"


def build_analyst_graph() -> StateGraph:
    g = StateGraph(AnalystState)

    g.add_node("ingest", ingest_node)
    g.add_node("triage", triage_node)
    g.add_node("cluster", cluster_node)
    g.add_node("stance", stance_node)
    g.add_node("quotes", quotes_node)
    g.add_node("aggregate", aggregate_node)
    g.add_node("render_brief", render_brief_node)

    g.set_entry_point("ingest")

    g.add_conditional_edges("ingest", _after_ingest, {"triage": "triage", END: END})
    g.add_edge("triage", "cluster")
    g.add_edge("cluster", "stance")
    g.add_edge("stance", "quotes")
    g.add_edge("quotes", "aggregate")
    g.add_edge("aggregate", "render_brief")
    g.add_edge("render_brief", END)

    return g


_graph = build_analyst_graph()
#: Compiled without a checkpointer -- unit tests and callers without Postgres.
_compiled_no_checkpoint = _graph.compile()


def thread_id_for(org_id: int, week_of: str, run_id: int) -> str:
    return f"analyst:{org_id}:{week_of}:{run_id}"


def week_of_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def current_week_of() -> date:
    return week_of_monday(date.today())


async def run_analyst_pipeline(
    org_id: int,
    week_of: date,
    run_id: int,
    session_local,
    redis_client=None,
    *,
    use_checkpointer: bool = True,
    database_url: Optional[str] = None,
) -> AnalystState:
    """Run graph #2 once for ``org_id``'s ``week_of`` Analyst run.

    ``session_local`` is an ``async_sessionmaker`` bound to a fresh engine
    (Celery tasks must not reuse a module-level engine across
    ``asyncio.run()`` calls -- see ``backend.database.build_session_factory``).
    ``use_checkpointer=False`` skips Postgres checkpointing entirely; unit
    tests and any environment without a reachable Postgres use this path.
    """
    from backend.pipeline.analyst_templates import get_analyst_templates
    from backend.utils.org_lookups import get_org_llm_config

    week_of_str = week_of.isoformat()
    initial_state = new_initial_analyst_state(org_id, week_of_str, run_id)
    # thread_id is scoped by run_id (not just org_id/week_of) so a second
    # run for the same org/week can never resume -- and thereby silently
    # no-op against -- an earlier run's already-``END`` checkpoint. run_id
    # is threaded through *config* (never re-derived from checkpointed
    # state) so every node call sees the run_id this specific invocation
    # was made for, even across a resumed/retried checkpoint.
    thread_id = thread_id_for(org_id, week_of_str, run_id)

    # Fetched once per pipeline run (not once per node) -- see the M3
    # review finding "cache get_analyst_templates + org LLM config once per
    # run". Threaded through config rather than state because OrgLLMConfig
    # is an ORM object, not checkpoint-safe state.
    async with session_local() as db:
        cached_llm_config = await get_org_llm_config(db, org_id)
        cached_templates = await get_analyst_templates(db, org_id)

    config = {
        "configurable": {
            "session_local": session_local,
            "redis_client": redis_client,
            "thread_id": thread_id,
            "run_id": run_id,
            "llm_config": cached_llm_config,
            "templates": cached_templates,
        }
    }

    if not use_checkpointer:
        return await _compiled_no_checkpoint.ainvoke(initial_state, config=config)

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from backend.database import DATABASE_URL

    conn_string = _psycopg_conn_string(database_url or DATABASE_URL)
    async with AsyncPostgresSaver.from_conn_string(conn_string) as saver:
        compiled = _graph.compile(checkpointer=saver)

        # Same resume trick as graph #1's run_pipeline: LangGraph only
        # continues past already-completed nodes when the input is `None`
        # for a thread_id with existing checkpoint history.
        existing = await compiled.aget_state(config)
        run_input = None if existing.metadata is not None else initial_state
        return await compiled.ainvoke(run_input, config=config)
