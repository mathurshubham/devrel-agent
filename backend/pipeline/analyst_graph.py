"""Graph #2 wiring (PRD V7 §5.6): a real ``StateGraph``, Postgres-checkpointed
exactly like graph #1 (``backend.pipeline.graph``) -- same
``langgraph-checkpoint-postgres`` tables, same resume semantics, different
``thread_id`` namespace so the two graphs' checkpoints never collide:

    ingest -> triage -> cluster -> stance -> quotes -> aggregate -> render_brief

``thread_id = f"analyst:{org_id}:{week_of}"``: a retried Celery task for the
same ``(org_id, week_of)`` resumes from the last completed node instead of
re-ingesting (and re-billing Apify) or re-running LLM calls already done.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from langgraph.graph import END, StateGraph

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


def thread_id_for(org_id: int, week_of: str) -> str:
    return f"analyst:{org_id}:{week_of}"


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
    week_of_str = week_of.isoformat()
    initial_state = new_initial_analyst_state(org_id, week_of_str, run_id)
    thread_id = thread_id_for(org_id, week_of_str)
    config = {
        "configurable": {
            "session_local": session_local,
            "redis_client": redis_client,
            "thread_id": thread_id,
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
