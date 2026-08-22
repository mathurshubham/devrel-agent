"""Shared state threaded through the reply-pipeline LangGraph (graph #1).

Everything here must survive a round-trip through the Postgres checkpointer
(``langgraph-checkpoint-postgres`` serializes state between node hops), so it
is deliberately plain dicts/lists/primitives -- no ORM instances, enums, or
other non-trivially-serializable objects. Platform/status values are stored
as their ``.value`` strings and converted to the real enum only where they
touch the ORM (persist_gate).

Non-serializable, per-run resources (a DB session factory, a Redis client)
are NOT part of this state -- they are threaded through via the LangGraph
``config["configurable"]`` mapping instead, which the checkpointer never
persists. See ``backend.pipeline.graph``.
"""
from typing import Any, Dict, List, Optional, TypedDict


class PipelineState(TypedDict, total=False):
    # Identity / run metadata
    campaign_id: int
    org_id: int
    platform: str  # PlatformEnum.value, e.g. "REDDIT"
    scheduled_ts: float

    # ingest -> prefilter
    posts: List[Dict[str, Any]]  # normalized post dicts (backend.ingestion.normalize contract)
    dropped: List[Dict[str, Any]]  # [{"post_id": ..., "reason": ...}]

    # scout -> token_budget -> strategist
    selections: List[Dict[str, Any]]  # [{post_id, angle_name, reply_type, target_comment_id, confidence, reasoning}]
    truncated_content: Dict[str, Dict[str, Any]]  # post_id -> {"content": ..., "top_comments": [...], "truncated": bool}

    # strategist -> finalize -> persist_gate
    drafts: List[Dict[str, Any]]

    # Bookkeeping
    errors: List[str]
    terminal: bool
    terminal_reason: Optional[str]
    persisted_draft_ids: List[int]


def new_initial_state(campaign_id: int, scheduled_ts: float) -> PipelineState:
    return PipelineState(
        campaign_id=campaign_id,
        org_id=0,
        platform="",
        scheduled_ts=scheduled_ts,
        posts=[],
        dropped=[],
        selections=[],
        truncated_content={},
        drafts=[],
        errors=[],
        terminal=False,
        terminal_reason=None,
        persisted_draft_ids=[],
    )
