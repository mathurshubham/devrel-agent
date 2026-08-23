"""The seven Analyst-pipeline nodes (PRD V7 §5.6):

    ingest -> triage -> cluster -> stance -> quotes -> aggregate -> render_brief

Ports ``social-agent``'s ``AnalystService`` chain onto LangGraph nodes with
structured outputs (``backend.pipeline.llm_transport``) instead of regex JSON
scraping, and org-scoped pillar taxonomy / watch-list data instead of the
MVP's hardcoded constants (PRD V7 §5.6, §9).

Every per-post LLM step (triage/cluster/stance/quotes) degrades gracefully on
failure -- a bad LLM call defaults that post's field(s) rather than dropping
the post -- and runs with concurrency <= 5, same discipline as the ported
``AnalystService._classify_all``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from sqlalchemy import select

from backend.models import (
    AnalystRun,
    IntelBrief,
    Organization,
    PostClassification,
    QuoteWorthyClaim,
    StanceObservation,
    SystemLog,
    TargetAuthor,
    TopicCluster,
    now_utc,
)
from backend.pipeline.analyst_ingest import gather_analyst_posts
from backend.pipeline.analyst_pillars import OTHER_PILLAR, get_pillar_taxonomy, pillar_tags, taxonomy_block
from backend.pipeline.analyst_schemas import (
    VALID_STANCES,
    ClusterResult,
    QuotesResult,
    StanceResult,
    TriageResult,
    confidence_to_float,
)
from backend.pipeline.analyst_state import AnalystState
from backend.pipeline.analyst_templates import get_analyst_templates, render
from backend.pipeline.llm_transport import (
    llm_call_kwargs,
    resolve_model,
    structured_completion,
    text_completion,
)
from backend.utils.cost_guard import CostLimitExceeded, check_and_record_llm_usage
from backend.utils.org_lookups import get_active_apify_vault_tokens, get_org_llm_config, get_org_settings
from backend.utils.tokenizer import count_tokens

logger = logging.getLogger(__name__)

#: Per-post LLM calls run concurrently but bounded (PRD V7 §5.6).
CONCURRENCY = 5

#: How far back cross-week dedup (``_previously_classified_post_ids``) looks
#: for a post already classified in an earlier run -- unbounded would mean
#: every ingest scans the org's entire classification history.
_DEDUP_LOOKBACK_WEEKS = 8

#: Sentinel distinguishing "config carries no cached value" from "config
#: explicitly carries ``None``" (e.g. an org genuinely has no OrgLLMConfig
#: row yet) -- ``dict.get(key, _UNSET)`` tells those two cases apart so a
#: pre-fetched ``None`` isn't mistaken for "not cached, go fetch it".
_UNSET = object()


async def _check_cost_cap(
    org_id: int, estimated_tokens: int, model: str, llm_config, redis_client
) -> Optional[str]:
    """Pre-dispatch cap check -- mirrors graph #1's ``persist_gate_node``.

    Returns an error message if the org's daily-token/monthly-cost cap was
    just breached (the caller must stop dispatching further LLM calls for
    this run), or ``None`` if the call may proceed. ``redis_client is None``
    means no cap store is reachable (unit tests, or a caller that opted
    out) -- degrade to "can't check, proceed unmetered" rather than crash,
    same as the metering-only ``record_llm_usage`` this replaces used to.
    """
    if redis_client is None:
        return None
    try:
        await check_and_record_llm_usage(
            org_id=org_id,
            estimated_tokens=estimated_tokens,
            model=model,
            r=redis_client,
            db=None,
            llm_config=llm_config,
        )
        return None
    except CostLimitExceeded as exc:
        return str(exc)


async def _fail_run_cost_limit(session_local, run_id: Optional[int], org_id: int, message: str) -> None:
    """Terminates an Analyst run cleanly on a cost-cap breach: the
    ``AnalystRun`` row is marked FAILED (reason cost_limit) and the breach
    is logged -- so a capped-out run never leaves a half-written brief or a
    row stuck RUNNING."""
    if run_id is None:
        logger.error("Analyst run cost-limit breach for org=%s with no run_id to fail: %s", org_id, message)
        return
    async with session_local() as db:
        run = await db.get(AnalystRun, run_id)
        if run and run.status not in ("COMPLETED", "FAILED"):
            run.status = "FAILED"
            run.finished_at = now_utc()
        await _log_system(
            db, org_id, "ERROR", "pipeline.analyst.cost_limit",
            f"Analyst run {run_id} terminated (reason=cost_limit): {message}",
        )
        await db.commit()

#: Truncate post content before it goes into any prompt -- ported from
#: social-agent's ``AnalystService._classify_post`` ([:1500]).
_POST_TEXT_CHARS = 1500


def _config(cfg: dict) -> dict:
    return cfg.get("configurable", {})


async def _log_system(db, org_id: int, level: str, module: str, message: str) -> None:
    db.add(SystemLog(org_id=org_id, level=level, module=module, message=message))
    await db.flush()


def _base_classification(post: dict, *, decision: str) -> dict:
    return {
        "post_id": post.get("post_id"),
        "author": post.get("author_name") or post.get("author") or "",
        "author_title": post.get("author_headline") or "",
        "url": post.get("url", ""),
        "platform": post.get("platform", ""),
        "engagement_score": int(post.get("engagement_score", 0) or 0),
        "decision": decision,
        "relevance_score": None,
        "signal_score": None,
        "buyer_persona": "OTHER",
        "watch_list_tier": "NONE",
        "primary_pillar": OTHER_PILLAR,
        "secondary_pillars": [],
        "stance": "NEUTRAL",
        "confidence": 0.5,
        "evidence_quote": "",
        "quotes": [],
    }


def _post_placeholders(post: dict) -> dict:
    return {
        "{POST_TEXT}": (post.get("content") or "")[:_POST_TEXT_CHARS],
        "{AUTHOR_NAME}": post.get("author_name") or post.get("author") or "",
        "{AUTHOR_TITLE}": post.get("author_headline") or "",
        "{AUTHOR_COMPANY}": "",
    }


async def _watchlist_block(db, org_id: int) -> str:
    """Org watch-list names by tier, appended to the triage prompt so
    ``watch_list_tier`` reflects this org's actual TargetAuthor data rather
    than the seeded prompt's illustrative example names (PRD V7 §5.6/§9:
    "MVP hardcoded Tier-1 names in code -- moved to data")."""
    rows = (await db.execute(select(TargetAuthor).where(TargetAuthor.org_id == org_id))).scalars().all()
    if not rows:
        return ""
    by_tier: dict[int, list[str]] = defaultdict(list)
    for row in rows:
        by_tier[row.tier or 2].append(row.name)
    lines = [f"Tier {tier}: {', '.join(names)}" for tier, names in sorted(by_tier.items())]
    return (
        "\n\nORG WATCH-LIST (use these names -- not the example names above -- "
        "when assigning watch_list_tier):\n" + "\n".join(lines)
    )


# ---------------------------------------------------------------------------
# 1. ingest
# ---------------------------------------------------------------------------


async def _previously_classified_post_ids(db, org_id: int, week_of: date) -> set:
    """Post ids already classified in an earlier week for this org, within
    the last ``_DEDUP_LOOKBACK_WEEKS`` weeks (PRD V7 §5.6 cross-week dedup).
    Reads the whole ``source_meta`` blob back in Python rather than a JSONB
    path operator, so this works the same way against Postgres or aiosqlite
    in tests.

    Bounded to a rolling lookback window rather than the org's entire
    classification history -- unbounded, every ingest would scan a
    steadily growing ``PostClassification`` table just to dedupe against
    weeks so old they're no longer operationally relevant.
    """
    cutoff = week_of - timedelta(weeks=_DEDUP_LOOKBACK_WEEKS)
    stmt = (
        select(PostClassification.source_meta)
        .join(AnalystRun, AnalystRun.id == PostClassification.run_id)
        .where(
            AnalystRun.org_id == org_id,
            AnalystRun.week_of != week_of,
            AnalystRun.week_of >= cutoff,
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    ids: set = set()
    for meta in rows:
        if isinstance(meta, dict) and meta.get("post_id"):
            ids.add(meta["post_id"])
    return ids


async def ingest_node(state: AnalystState, config: RunnableConfig) -> dict:
    cfg = _config(config)
    session_local = cfg["session_local"]
    redis_client = cfg.get("redis_client")
    org_id = state["org_id"]
    # run_id is created before the graph is invoked and threaded through
    # config, not re-derived from checkpointed state (which a resumed/
    # retried checkpoint could otherwise serve stale) -- see
    # backend.pipeline.analyst_graph.run_analyst_pipeline.
    run_id = cfg.get("run_id", state.get("run_id"))
    week_of_date = date.fromisoformat(state["week_of"])

    async with session_local() as db:
        org = await db.get(Organization, org_id)
        if not org:
            return {"terminal": True, "terminal_reason": "org_missing"}
        if not org.is_active:
            # Same guard as backend.tasks.scheduler.scheduler_tick applies
            # to reply-pipeline campaigns -- a deactivated org must not get
            # an Analyst run either, whether dispatched by the weekly beat
            # (which already filters on Organization.is_active before
            # creating the run row) or an on-demand trigger racing a
            # deactivation.
            return {"terminal": True, "terminal_reason": "org_inactive"}

        org_settings = await get_org_settings(db, org_id)
        vault_tokens = await get_active_apify_vault_tokens(db, org_id)

        posts, competitor_posts, source_errors = await gather_analyst_posts(
            db, org_id, org_settings, vault_tokens, redis_client=redis_client
        )

        seen_ids = await _previously_classified_post_ids(db, org_id, week_of_date)
        fresh_posts = [p for p in posts if p.get("post_id") not in seen_ids]
        deduped = len(posts) - len(fresh_posts)

        await _log_system(
            db, org_id, "INFO", "pipeline.analyst.ingest",
            f"Analyst run {run_id}: ingested {len(posts)} post(s) ({deduped} already "
            f"classified in a prior week), {len(competitor_posts)} competitor post(s), "
            f"{len(source_errors)} source error(s)",
        )

        if not fresh_posts and not competitor_posts:
            run = await db.get(AnalystRun, run_id)
            if run:
                run.status = "COMPLETED"
                run.finished_at = now_utc()
            await db.commit()
            return {"posts": [], "competitor_posts": [], "terminal": True, "terminal_reason": "no_posts"}

        await db.commit()

    return {
        "posts": fresh_posts,
        "competitor_posts": competitor_posts,
        "errors": state.get("errors", []) + source_errors,
    }


# ---------------------------------------------------------------------------
# 2. triage
# ---------------------------------------------------------------------------


async def triage_node(state: AnalystState, config: RunnableConfig) -> dict:
    if state.get("terminal"):
        return {}
    posts = state.get("posts", [])
    if not posts:
        return {"classifications": []}

    cfg = _config(config)
    session_local = cfg["session_local"]
    redis_client = cfg.get("redis_client")
    org_id = state["org_id"]
    run_id = cfg.get("run_id", state.get("run_id"))

    cached_llm_config = cfg.get("llm_config", _UNSET)
    cached_templates = cfg.get("templates", _UNSET)
    async with session_local() as db:
        llm_config = cached_llm_config if cached_llm_config is not _UNSET else await get_org_llm_config(db, org_id)
        templates = cached_templates if cached_templates is not _UNSET else await get_analyst_templates(db, org_id)
        watchlist = await _watchlist_block(db, org_id)

    template = templates.get("triage", "")
    if not llm_config or not llm_config.model_name or not template:
        classifications = [_base_classification(p, decision="PROCESS_LIGHT") for p in posts]
        reason = "triage: no LLM configured" if not llm_config or not llm_config.model_name else "triage: no template"
        return {"classifications": classifications, "errors": state.get("errors", []) + [reason]}

    model = resolve_model(llm_config)
    call_kwargs = llm_call_kwargs(llm_config)
    sem = asyncio.Semaphore(CONCURRENCY)
    cost_limit = {"hit": False, "message": ""}

    async def _triage_one(post: dict) -> dict:
        base = _base_classification(post, decision="PROCESS_LIGHT")
        if cost_limit["hit"]:
            return base
        prompt = render(template, _post_placeholders(post)) + watchlist
        async with sem:
            if cost_limit["hit"]:
                return base
            breach = await _check_cost_cap(
                org_id, count_tokens(model, prompt), model, llm_config, redis_client
            )
            if breach:
                cost_limit["hit"] = True
                cost_limit["message"] = breach
                return base
            try:
                parsed, response = await structured_completion(prompt, model, TriageResult, call_kwargs)
            except Exception as exc:  # noqa: BLE001 - degrade to PROCESS_LIGHT, never drop the post
                logger.warning("Analyst triage failed for %s: %s", post.get("post_id"), exc)
                return base
            base.update(
                decision=parsed.decision,
                relevance_score=parsed.relevance_score,
                signal_score=parsed.signal_score,
                buyer_persona=parsed.buyer_persona or "OTHER",
                watch_list_tier=parsed.watch_list_tier or "NONE",
            )
            return base

    classifications = list(await asyncio.gather(*[_triage_one(p) for p in posts]))

    if cost_limit["hit"]:
        await _fail_run_cost_limit(session_local, run_id, org_id, cost_limit["message"])
        return {"classifications": classifications, "terminal": True, "terminal_reason": "cost_limit"}

    full = sum(1 for c in classifications if c["decision"] == "PROCESS_FULL")
    skipped = sum(1 for c in classifications if c["decision"] == "SKIP")
    logger.info(
        "Analyst triage: %d full, %d light, %d skipped (of %d)",
        full, len(classifications) - full - skipped, skipped, len(classifications),
    )
    return {"classifications": classifications}


# ---------------------------------------------------------------------------
# 3. cluster
# ---------------------------------------------------------------------------


async def cluster_node(state: AnalystState, config: RunnableConfig) -> dict:
    if state.get("terminal"):
        return {}
    classifications = state.get("classifications", [])
    survivors = [c for c in classifications if c.get("decision") != "SKIP"]
    if not survivors:
        return {"classifications": classifications}

    cfg = _config(config)
    session_local = cfg["session_local"]
    redis_client = cfg.get("redis_client")
    org_id = state["org_id"]
    run_id = cfg.get("run_id", state.get("run_id"))
    posts_by_id = {p["post_id"]: p for p in state.get("posts", [])}

    cached_llm_config = cfg.get("llm_config", _UNSET)
    cached_templates = cfg.get("templates", _UNSET)
    async with session_local() as db:
        llm_config = cached_llm_config if cached_llm_config is not _UNSET else await get_org_llm_config(db, org_id)
        org_settings = await get_org_settings(db, org_id)
        templates = cached_templates if cached_templates is not _UNSET else await get_analyst_templates(db, org_id)

    template = templates.get("cluster", "")
    tax_block = taxonomy_block(get_pillar_taxonomy(org_settings))

    if not llm_config or not llm_config.model_name or not template:
        for c in survivors:
            c["primary_pillar"] = OTHER_PILLAR
            c["secondary_pillars"] = []
        return {"classifications": classifications}

    model = resolve_model(llm_config)
    call_kwargs = llm_call_kwargs(llm_config)
    sem = asyncio.Semaphore(CONCURRENCY)
    cost_limit = {"hit": False, "message": ""}

    async def _cluster_one(c: dict) -> None:
        if cost_limit["hit"]:
            return
        post = posts_by_id.get(c["post_id"], {})
        prompt = render(template, _post_placeholders(post)) + tax_block
        async with sem:
            if cost_limit["hit"]:
                return
            breach = await _check_cost_cap(
                org_id, count_tokens(model, prompt), model, llm_config, redis_client
            )
            if breach:
                cost_limit["hit"] = True
                cost_limit["message"] = breach
                return
            try:
                parsed, response = await structured_completion(prompt, model, ClusterResult, call_kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Analyst cluster failed for %s: %s", c.get("post_id"), exc)
                c["primary_pillar"] = OTHER_PILLAR
                c["secondary_pillars"] = []
                return
            c["primary_pillar"] = parsed.primary_pillar or OTHER_PILLAR
            c["secondary_pillars"] = parsed.secondary_pillars or []

    await asyncio.gather(*[_cluster_one(c) for c in survivors])

    if cost_limit["hit"]:
        await _fail_run_cost_limit(session_local, run_id, org_id, cost_limit["message"])
        return {"classifications": classifications, "terminal": True, "terminal_reason": "cost_limit"}

    return {"classifications": classifications}


# ---------------------------------------------------------------------------
# 4. stance
# ---------------------------------------------------------------------------


async def stance_node(state: AnalystState, config: RunnableConfig) -> dict:
    if state.get("terminal"):
        return {}
    classifications = state.get("classifications", [])
    survivors = [c for c in classifications if c.get("decision") != "SKIP"]
    if not survivors:
        return {"classifications": classifications}

    cfg = _config(config)
    session_local = cfg["session_local"]
    redis_client = cfg.get("redis_client")
    org_id = state["org_id"]
    run_id = cfg.get("run_id", state.get("run_id"))
    posts_by_id = {p["post_id"]: p for p in state.get("posts", [])}

    cached_llm_config = cfg.get("llm_config", _UNSET)
    cached_templates = cfg.get("templates", _UNSET)
    async with session_local() as db:
        llm_config = cached_llm_config if cached_llm_config is not _UNSET else await get_org_llm_config(db, org_id)
        templates = cached_templates if cached_templates is not _UNSET else await get_analyst_templates(db, org_id)

    template = templates.get("stance", "")
    if not llm_config or not llm_config.model_name or not template:
        return {"classifications": classifications}

    model = resolve_model(llm_config)
    call_kwargs = llm_call_kwargs(llm_config)
    sem = asyncio.Semaphore(CONCURRENCY)
    cost_limit = {"hit": False, "message": ""}

    async def _stance_one(c: dict) -> None:
        if cost_limit["hit"]:
            return
        post = posts_by_id.get(c["post_id"], {})
        values = {**_post_placeholders(post), "{PILLAR_TAG}": c.get("primary_pillar", OTHER_PILLAR)}
        prompt = render(template, values)
        async with sem:
            if cost_limit["hit"]:
                return
            breach = await _check_cost_cap(
                org_id, count_tokens(model, prompt), model, llm_config, redis_client
            )
            if breach:
                cost_limit["hit"] = True
                cost_limit["message"] = breach
                return
            try:
                parsed, response = await structured_completion(prompt, model, StanceResult, call_kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Analyst stance failed for %s: %s", c.get("post_id"), exc)
                return
            stance = parsed.stance if parsed.stance in VALID_STANCES else "NEUTRAL"
            c["stance"] = stance
            c["confidence"] = confidence_to_float(parsed.confidence)
            c["evidence_quote"] = parsed.evidence_quote or ""

    await asyncio.gather(*[_stance_one(c) for c in survivors])

    if cost_limit["hit"]:
        await _fail_run_cost_limit(session_local, run_id, org_id, cost_limit["message"])
        return {"classifications": classifications, "terminal": True, "terminal_reason": "cost_limit"}

    return {"classifications": classifications}


# ---------------------------------------------------------------------------
# 5. quotes
# ---------------------------------------------------------------------------


def _normalize_quotes(items: list) -> list[dict]:
    out: list[dict] = []
    for item in items or []:
        if isinstance(item, dict):
            text = str(item.get("text") or "")
            angle = item.get("angle")
        elif isinstance(item, str):
            text, angle = item, None
        else:
            continue
        if text:
            out.append({"text": text, "angle": angle})
    return out


async def quotes_node(state: AnalystState, config: RunnableConfig) -> dict:
    if state.get("terminal"):
        return {}
    classifications = state.get("classifications", [])
    full = [c for c in classifications if c.get("decision") == "PROCESS_FULL"]
    if not full:
        return {"classifications": classifications}

    cfg = _config(config)
    session_local = cfg["session_local"]
    redis_client = cfg.get("redis_client")
    org_id = state["org_id"]
    run_id = cfg.get("run_id", state.get("run_id"))
    posts_by_id = {p["post_id"]: p for p in state.get("posts", [])}

    cached_llm_config = cfg.get("llm_config", _UNSET)
    cached_templates = cfg.get("templates", _UNSET)
    async with session_local() as db:
        llm_config = cached_llm_config if cached_llm_config is not _UNSET else await get_org_llm_config(db, org_id)
        templates = cached_templates if cached_templates is not _UNSET else await get_analyst_templates(db, org_id)

    template = templates.get("quotes", "")
    if not llm_config or not llm_config.model_name or not template:
        return {"classifications": classifications}

    model = resolve_model(llm_config)
    call_kwargs = llm_call_kwargs(llm_config)
    sem = asyncio.Semaphore(CONCURRENCY)
    cost_limit = {"hit": False, "message": ""}

    async def _quotes_one(c: dict) -> None:
        if cost_limit["hit"]:
            return
        post = posts_by_id.get(c["post_id"], {})
        values = {
            **_post_placeholders(post),
            "{PILLAR_TAG}": c.get("primary_pillar", OTHER_PILLAR),
            "{STANCE_LABEL}": c.get("stance", "NEUTRAL"),
        }
        prompt = render(template, values)
        async with sem:
            if cost_limit["hit"]:
                return
            breach = await _check_cost_cap(
                org_id, count_tokens(model, prompt), model, llm_config, redis_client
            )
            if breach:
                cost_limit["hit"] = True
                cost_limit["message"] = breach
                return
            try:
                parsed, response = await structured_completion(prompt, model, QuotesResult, call_kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Analyst quotes failed for %s: %s", c.get("post_id"), exc)
                return
            c["quotes"] = _normalize_quotes([q.model_dump() for q in parsed.quotes])

    await asyncio.gather(*[_quotes_one(c) for c in full])

    if cost_limit["hit"]:
        await _fail_run_cost_limit(session_local, run_id, org_id, cost_limit["message"])
        return {"classifications": classifications, "terminal": True, "terminal_reason": "cost_limit"}

    return {"classifications": classifications}


# ---------------------------------------------------------------------------
# 6. aggregate (pure Python -- no LLM call)
# ---------------------------------------------------------------------------


def week_of_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def compute_pillar_counts(processed: list[dict]) -> dict[str, dict]:
    """pillar -> {"count": n, "stance_counts": {...}, "post_ids": [...]}."""
    by_pillar: dict[str, list[dict]] = defaultdict(list)
    for c in processed:
        by_pillar[c.get("primary_pillar") or OTHER_PILLAR].append(c)

    out: dict[str, dict] = {}
    for pillar, items in by_pillar.items():
        stance_counts = Counter(c.get("stance", "NEUTRAL") for c in items)
        out[pillar] = {
            "count": len(items),
            "stance_counts": dict(stance_counts),
            "post_ids": [c["post_id"] for c in items],
        }
    return out


def compute_momentum(prev_counts: dict[str, int], curr_counts: dict[str, int]) -> dict[str, dict]:
    """pillar -> {"prev", "curr", "delta"} week-over-week (PRD V7 §5.6)."""
    all_pillars = set(prev_counts) | set(curr_counts)
    return {
        p: {
            "prev": prev_counts.get(p, 0),
            "curr": curr_counts.get(p, 0),
            "delta": curr_counts.get(p, 0) - prev_counts.get(p, 0),
        }
        for p in all_pillars
    }


async def aggregate_node(state: AnalystState, config: RunnableConfig) -> dict:
    if state.get("terminal"):
        return {}
    classifications = state.get("classifications", [])

    cfg = _config(config)
    session_local = cfg["session_local"]
    org_id = state["org_id"]
    run_id = cfg.get("run_id", state.get("run_id"))
    week_of_date = date.fromisoformat(state["week_of"])

    skipped = [c for c in classifications if c.get("decision") == "SKIP"]
    processed = [c for c in classifications if c.get("decision") != "SKIP"]
    full = [c for c in processed if c.get("decision") == "PROCESS_FULL"]
    triage_counts = {
        "PROCESS_FULL": len(full),
        "PROCESS_LIGHT": len(processed) - len(full),
        "SKIP": len(skipped),
        "total": len(classifications),
    }

    pillar_data = compute_pillar_counts(processed)

    async with session_local() as db:
        org_settings = await get_org_settings(db, org_id)
        valid_pillars = set(pillar_tags(get_pillar_taxonomy(org_settings)))

        for c in classifications:
            db.add(
                PostClassification(
                    run_id=run_id,
                    source_meta={
                        "post_id": c.get("post_id"),
                        "author": c.get("author", ""),
                        "author_title": c.get("author_title", ""),
                        "url": c.get("url", ""),
                        "platform": c.get("platform", ""),
                        "engagement_score": c.get("engagement_score", 0),
                        "primary_pillar": c.get("primary_pillar"),
                        "secondary_pillars": c.get("secondary_pillars", []),
                        "stance": c.get("stance"),
                        "reason_short": c.get("reason_short", ""),
                    },
                    decision=c.get("decision"),
                    relevance=c.get("relevance_score"),
                    signal=c.get("signal_score"),
                    buyer_persona=c.get("buyer_persona"),
                    watch_tier=c.get("watch_list_tier"),
                )
            )

        for pillar, data in pillar_data.items():
            db.add(
                TopicCluster(
                    run_id=run_id,
                    pillar=pillar,
                    count=data["count"],
                    posts=data["post_ids"][:10],
                )
            )

        for c in processed:
            # Every processed post gets a StanceObservation, including
            # OTHER (the degrade-to-default pillar when cluster_node has
            # no LLM/template configured, or the classifier genuinely
            # can't fit the post into the taxonomy) -- OTHER is not itself
            # one of the org's taxonomy tags, so it must be allowed
            # explicitly here or every degraded run silently records zero
            # stance observations. A pillar that is neither a taxonomy tag
            # nor OTHER (a hallucinated tag) is still dropped.
            pillar = c.get("primary_pillar") or OTHER_PILLAR
            if pillar not in valid_pillars and pillar != OTHER_PILLAR:
                continue
            db.add(
                StanceObservation(
                    run_id=run_id,
                    post_ref=c.get("url") or c.get("post_id") or "",
                    stance=c.get("stance", "NEUTRAL"),
                    confidence=float(c.get("confidence", 0.5) or 0.5),
                    evidence_quote=c.get("evidence_quote", ""),
                )
            )

        for c in full:
            for q in c.get("quotes", []):
                db.add(
                    QuoteWorthyClaim(
                        run_id=run_id,
                        post_ref=c.get("url") or c.get("post_id") or "",
                        quote=q.get("text", ""),
                        author=c.get("author", ""),
                    )
                )

        prev_monday = week_of_monday(week_of_date - timedelta(days=7))
        prev_stmt = (
            select(TopicCluster.pillar, TopicCluster.count)
            .join(AnalystRun, AnalystRun.id == TopicCluster.run_id)
            .where(AnalystRun.org_id == org_id, AnalystRun.week_of == prev_monday)
        )
        prev_rows = (await db.execute(prev_stmt)).all()
        prev_week_counts = {pillar: count for pillar, count in prev_rows}

        await _log_system(
            db, org_id, "INFO", "pipeline.analyst.aggregate",
            f"Analyst run {run_id}: {len(pillar_data)} pillar(s), triage={triage_counts}",
        )
        await db.commit()

    return {
        "classifications": classifications,
        "triage_counts": triage_counts,
        "prev_week_counts": prev_week_counts,
        "pillar_summaries": [
            {"pillar": pillar, "count": data["count"], "stance_counts": data["stance_counts"]}
            for pillar, data in pillar_data.items()
        ],
    }


# ---------------------------------------------------------------------------
# 7. render_brief
# ---------------------------------------------------------------------------



async def render_brief_node(state: AnalystState, config: RunnableConfig) -> dict:
    if state.get("terminal"):
        return {}

    cfg = _config(config)
    session_local = cfg["session_local"]
    redis_client = cfg.get("redis_client")
    org_id = state["org_id"]
    run_id = cfg.get("run_id", state.get("run_id"))
    week_of_str = state["week_of"]
    classifications = state.get("classifications", [])
    competitor_posts = state.get("competitor_posts", [])
    prev_week_counts = state.get("prev_week_counts", {})
    triage_counts = state.get("triage_counts", {})

    processed = [c for c in classifications if c.get("decision") != "SKIP"]

    brief_posts = [
        {
            "post_id": c["post_id"],
            "author": c.get("author", ""),
            "author_title": c.get("author_title", ""),
            "buyer_persona": c.get("buyer_persona", "OTHER"),
            "watch_list_tier": c.get("watch_list_tier", "NONE"),
            "primary_pillar": c.get("primary_pillar", OTHER_PILLAR),
            "secondary_pillars": c.get("secondary_pillars", []),
            "stance": c.get("stance", "NEUTRAL"),
            "quotes": c.get("quotes", []),
            "url": c.get("url", ""),
        }
        for c in processed
    ]

    cached_llm_config = cfg.get("llm_config", _UNSET)
    cached_templates = cfg.get("templates", _UNSET)
    async with session_local() as db:
        llm_config = cached_llm_config if cached_llm_config is not _UNSET else await get_org_llm_config(db, org_id)
        templates = cached_templates if cached_templates is not _UNSET else await get_analyst_templates(db, org_id)

    template = templates.get("brief") or ""
    if template:
        prompt = render(template, {"{WEEK_OF}": week_of_str})
    else:
        prompt = (
            f"Write the weekly Intel Brief — Week of {week_of_str}. Sections: TL;DR, "
            "Pillar Activity Summary, What Buyer Personas Are Saying, Watch-List Voices, "
            "Emerging Patterns, Content Recommendations."
        )

    prompt += (
        "\n\nINPUT DATA — classified posts collected this week (JSON):\n"
        + json.dumps(brief_posts, ensure_ascii=False)
    )

    if prev_week_counts:
        this_week_counts = Counter(c.get("primary_pillar", OTHER_PILLAR) for c in processed)
        momentum = compute_momentum(prev_week_counts, dict(this_week_counts))
        rising = [p for p, m in momentum.items() if m["delta"] > 0]
        falling = [p for p, m in momentum.items() if m["delta"] < 0]
        prompt += (
            "\n\nMOMENTUM vs PREVIOUS WEEK — use this in the Emerging Patterns section "
            "to highlight rising/falling pillars:\n"
            + json.dumps({"momentum": momentum, "rising": rising, "falling": falling}, ensure_ascii=False)
        )

    if triage_counts:
        prompt += (
            "\n\nTRIAGE SUMMARY this week (mention in TL;DR if notable):\n"
            + json.dumps(triage_counts, ensure_ascii=False)
        )

    if competitor_posts:
        by_comp: dict[str, list] = defaultdict(list)
        for p in competitor_posts:
            by_comp[p.get("competitor", "Unknown")].append(
                {
                    "platform": p.get("platform"),
                    "content": (p.get("content") or "")[:300],
                    "url": p.get("url"),
                    "engagement_score": p.get("engagement_score", 0),
                }
            )
        prompt += (
            "\n\nCOMPETITOR ACTIVITY this week — add a '## Competitive Watch' section. "
            "For each competitor list: top post, pillars they're engaging on, openings "
            "where we can differentiate:\n" + json.dumps(dict(by_comp), ensure_ascii=False)
        )

    model = resolve_model(llm_config)
    call_kwargs = llm_call_kwargs(llm_config)

    breach = await _check_cost_cap(org_id, count_tokens(model, prompt), model, llm_config, redis_client)
    if breach:
        await _fail_run_cost_limit(session_local, run_id, org_id, breach)
        # No IntelBrief is written -- a capped-out run must not leave a
        # half-written brief behind.
        return {"terminal": True, "terminal_reason": "cost_limit"}

    try:
        brief_md, response = await text_completion(prompt, model, call_kwargs)
    except Exception as exc:  # noqa: BLE001 - a brief that failed to generate must not crash the run
        # Mirror the cost-limit path: the run FAILS, no IntelBrief is written.
        # Persisting an error string as a "brief" poisons next week's
        # momentum inputs and shows a green COMPLETED chip over a failure.
        logger.error("Analyst render_brief failed for org=%s run=%s: %s", org_id, run_id, exc)
        async with session_local() as db:
            run = await db.get(AnalystRun, run_id)
            if run:
                run.status = "FAILED"
                run.finished_at = now_utc()
            await _log_system(
                db, org_id, "ERROR", "pipeline.analyst.render_brief",
                f"Analyst run {run_id}: brief generation failed: {exc}",
            )
            await db.commit()
        return {"terminal": True, "terminal_reason": "llm_error"}

    week_of_date = date.fromisoformat(week_of_str)
    async with session_local() as db:
        existing = (
            await db.execute(
                select(IntelBrief).where(IntelBrief.org_id == org_id, IntelBrief.week_of == week_of_date)
            )
        ).scalar_one_or_none()
        if existing:
            existing.content_md = brief_md
            brief_id = existing.id
        else:
            row = IntelBrief(org_id=org_id, week_of=week_of_date, content_md=brief_md)
            db.add(row)
            await db.flush()
            brief_id = row.id

        run = await db.get(AnalystRun, run_id)
        if run:
            run.status = "COMPLETED"
            run.finished_at = now_utc()

        await _log_system(
            db, org_id, "INFO", "pipeline.analyst.render_brief",
            f"Analyst run {run_id}: brief generated ({len(brief_md)} chars)",
        )
        await db.commit()

    return {"brief_id": brief_id, "terminal": True, "terminal_reason": "completed"}
