"""Graph #1 wiring (PRD V7 §5.3/§5.2 D5): a real ``StateGraph``, Postgres-checkpointed.

    ingest -> prefilter -> scout -> token_budget -> strategist -> finalize -> persist_gate

Checkpointing uses ``langgraph-checkpoint-postgres``'s ``AsyncPostgresSaver``
on ``DATABASE_URL``, keyed by ``thread_id = f"campaign:{campaign_id}:run:
{scheduled_ts}"``. A retried Celery task that reuses the same
``(campaign_id, scheduled_ts)`` therefore resumes from the last completed
node instead of re-running ``ingest`` (and re-billing Apify) -- see
``backend.tasks.workers.langgen_task``.
"""

from __future__ import annotations

import logging
from typing import Optional

from langgraph.graph import END, StateGraph

from backend.pipeline.nodes import (
    finalize_node,
    ingest_node,
    persist_gate_node,
    prefilter_node,
    scout_node,
    strategist_node,
    token_budget_node,
)
from backend.pipeline.state import PipelineState, new_initial_state

logger = logging.getLogger(__name__)


def _after_ingest(state: PipelineState) -> str:
    return END if state.get("terminal") else "prefilter"


def _after_prefilter(state: PipelineState) -> str:
    return "scout" if state.get("posts") else END


def _after_scout(state: PipelineState) -> str:
    return "token_budget" if state.get("selections") else END


def build_graph() -> StateGraph:
    g = StateGraph(PipelineState)

    g.add_node("ingest", ingest_node)
    g.add_node("prefilter", prefilter_node)
    g.add_node("scout", scout_node)
    g.add_node("token_budget", token_budget_node)
    g.add_node("strategist", strategist_node)
    g.add_node("finalize", finalize_node)
    g.add_node("persist_gate", persist_gate_node)

    g.set_entry_point("ingest")

    g.add_conditional_edges("ingest", _after_ingest, {"prefilter": "prefilter", END: END})
    g.add_conditional_edges("prefilter", _after_prefilter, {"scout": "scout", END: END})
    g.add_conditional_edges("scout", _after_scout, {"token_budget": "token_budget", END: END})
    g.add_edge("token_budget", "strategist")
    g.add_edge("strategist", "finalize")
    g.add_edge("finalize", "persist_gate")
    g.add_edge("persist_gate", END)

    return g


_graph = build_graph()
#: Compiled without a checkpointer -- used by unit tests and any caller that
#: doesn't need (or can't reach) Postgres for checkpoint storage.
_compiled_no_checkpoint = _graph.compile()


def _psycopg_conn_string(database_url: str) -> str:
    """``langgraph-checkpoint-postgres`` wants a psycopg-style URL; the rest
    of this codebase's ``DATABASE_URL`` is the asyncpg SQLAlchemy DSN."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


async def setup_checkpointer_tables(database_url: Optional[str] = None) -> None:
    """Create the checkpoint tables if they don't exist yet.

    Call once at worker startup (idempotent) -- see the ``worker_process_init``
    hook wiring in ``backend/celery_app.py``.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from backend.database import DATABASE_URL

    conn_string = _psycopg_conn_string(database_url or DATABASE_URL)
    async with AsyncPostgresSaver.from_conn_string(conn_string) as saver:
        await saver.setup()


def thread_id_for(campaign_id: int, scheduled_ts: float) -> str:
    return f"campaign:{campaign_id}:run:{scheduled_ts}"


async def run_pipeline(
    campaign_id: int,
    scheduled_ts: float,
    session_local,
    redis_client=None,
    *,
    use_checkpointer: bool = True,
    database_url: Optional[str] = None,
) -> PipelineState:
    """Run graph #1 once for ``campaign_id``.

    ``session_local`` is an ``async_sessionmaker`` bound to a fresh engine
    (see ``backend.database.build_session_factory`` -- Celery tasks must not
    reuse a module-level engine across ``asyncio.run()`` calls).
    ``use_checkpointer=False`` skips Postgres checkpointing entirely; unit
    tests and any environment without a reachable Postgres use this path.
    """
    initial_state = new_initial_state(campaign_id, scheduled_ts)
    thread_id = thread_id_for(campaign_id, scheduled_ts)
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

        # Resume semantics: LangGraph only continues past already-completed
        # nodes when the input is `None` for a thread_id with existing
        # checkpoint history -- passing a fresh initial_state again (even
        # with the same thread_id) starts a brand-new run from "ingest",
        # which would re-call Apify. A retried Celery task reuses the same
        # (campaign_id, scheduled_ts) -> same thread_id, so detect prior
        # progress and resume with `None` instead.
        existing = await compiled.aget_state(config)
        run_input = None if existing.metadata is not None else initial_state
        return await compiled.ainvoke(run_input, config=config)
