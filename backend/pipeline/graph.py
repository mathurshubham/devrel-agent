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
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


#: asyncpg/SQLAlchemy-asyncpg query-param names that mean something
#: different (or nothing) to psycopg's libpq-style connection string, keyed
#: to the psycopg name that expresses the same thing.
_ASYNCPG_TO_PSYCOPG_QUERY_PARAMS = {
    "ssl": "sslmode",
}


def _psycopg_conn_string(database_url: str) -> str:
    """``langgraph-checkpoint-postgres`` wants a psycopg-style URL; the rest
    of this codebase's ``DATABASE_URL`` is the asyncpg SQLAlchemy DSN.

    Swapping the ``postgresql+asyncpg://`` scheme is not the only
    difference: asyncpg/SQLAlchemy's asyncpg dialect spells "require TLS"
    as a ``ssl=require`` query param, while psycopg (libpq) spells the same
    thing ``sslmode=require`` and does not understand ``ssl=`` at all --
    passed straight through, a managed-Postgres DSN that required TLS via
    ``?ssl=require`` would have that parameter silently ignored by
    psycopg, either failing to connect or (depending on the provider)
    connecting unencrypted. Translate every known asyncpg-only query
    param name to its psycopg equivalent; anything else passes through
    unchanged.
    """
    url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    parts = urlsplit(url)
    if not parts.query:
        return url

    translated = [
        (_ASYNCPG_TO_PSYCOPG_QUERY_PARAMS.get(key, key), value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    new_query = urlencode(translated)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


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


async def purge_old_checkpoints(
    *, retention_days: int = 7, database_url: Optional[str] = None
) -> dict:
    """Delete checkpoint state older than ``retention_days`` (PRD V7 retention).

    ``langgraph-checkpoint-postgres`` never expires anything on its own --
    left alone, ``checkpoints``/``checkpoint_blobs``/``checkpoint_writes``
    grow unboundedly, and a checkpoint blob holds a full snapshot of
    pipeline state (including ingested post content) that would otherwise
    outlive whatever retention schedule the PRD sets for that data
    elsewhere.

    Deletes by *thread*: each ``thread_id`` is one campaign poll run
    (``backend.pipeline.graph.thread_id_for``). A thread is stale once its
    newest checkpoint's ``ts`` (a field every checkpoint's JSONB payload
    carries -- see ``langgraph.checkpoint.base.Checkpoint``) is older than
    the cutoff; every row for that thread across all three checkpoint
    tables is removed together, not just the ``checkpoints`` table, since a
    dangling ``checkpoint_blobs``/``checkpoint_writes`` row for a purged
    thread is exactly the same "checkpointed post content outliving
    retention" problem this exists to close.

    Call from a daily Celery beat task -- see
    ``backend.tasks.workers.purge_old_checkpoints_task``.
    """
    from psycopg import AsyncConnection

    from backend.database import DATABASE_URL

    conn_string = _psycopg_conn_string(database_url or DATABASE_URL)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    async with await AsyncConnection.connect(conn_string, autocommit=True) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT thread_id
                FROM checkpoints
                GROUP BY thread_id
                HAVING max((checkpoint ->> 'ts')::timestamptz) < %s
                """,
                (cutoff,),
            )
            rows = await cur.fetchall()
            stale_thread_ids = [r[0] for r in rows]

            if not stale_thread_ids:
                logger.info("purge_old_checkpoints: no threads older than %s", cutoff.isoformat())
                return {"threads_purged": 0, "cutoff": cutoff.isoformat()}

            # Writes and blobs first (they exist "under" a checkpoint row),
            # then the checkpoint rows themselves.
            await cur.execute(
                "DELETE FROM checkpoint_writes WHERE thread_id = ANY(%s)", (stale_thread_ids,)
            )
            await cur.execute(
                "DELETE FROM checkpoint_blobs WHERE thread_id = ANY(%s)", (stale_thread_ids,)
            )
            await cur.execute(
                "DELETE FROM checkpoints WHERE thread_id = ANY(%s)", (stale_thread_ids,)
            )

    logger.info(
        "purge_old_checkpoints: removed %d thread(s) with no checkpoint newer than %s",
        len(stale_thread_ids), cutoff.isoformat(),
    )
    return {"threads_purged": len(stale_thread_ids), "cutoff": cutoff.isoformat()}
