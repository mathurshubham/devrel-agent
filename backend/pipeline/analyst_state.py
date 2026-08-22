"""Shared state threaded through the Analyst LangGraph (graph #2, PRD V7 §5.6).

Same discipline as ``backend.pipeline.state`` for graph #1: everything here
must round-trip through the Postgres checkpointer, so it stays plain
dicts/lists/primitives. Non-serializable per-run resources (DB session
factory, Redis client) live in ``config["configurable"]`` instead -- see
``backend.pipeline.analyst_graph``.
"""
from typing import Any, Dict, List, Optional, TypedDict


class AnalystState(TypedDict, total=False):
    # Identity / run metadata
    org_id: int
    week_of: str  # ISO date string for the Monday of the analysis week
    run_id: int

    # ingest -> triage
    posts: List[Dict[str, Any]]  # normalized post dicts, source_meta-ready
    competitor_posts: List[Dict[str, Any]]  # raw, never classified -- brief input only
    dropped: List[Dict[str, Any]]  # [{"post_id": ..., "reason": ...}]

    # triage -> cluster -> stance -> quotes
    # One dict per post, accumulating fields as it moves through the chain.
    # Always present (including SKIP decisions) so aggregate can count them.
    classifications: List[Dict[str, Any]]

    # aggregate -> render_brief
    prev_week_counts: Dict[str, int]
    triage_counts: Dict[str, int]
    pillar_summaries: List[Dict[str, Any]]  # [{"pillar": ..., "count": ..., "post_ids": [...]}]

    # Bookkeeping
    errors: List[str]
    terminal: bool
    terminal_reason: Optional[str]
    brief_id: Optional[int]


def new_initial_analyst_state(org_id: int, week_of: str, run_id: int) -> AnalystState:
    return AnalystState(
        org_id=org_id,
        week_of=week_of,
        run_id=run_id,
        posts=[],
        competitor_posts=[],
        dropped=[],
        classifications=[],
        prev_week_counts={},
        triage_counts={},
        pillar_summaries=[],
        errors=[],
        terminal=False,
        terminal_reason=None,
        brief_id=None,
    )
