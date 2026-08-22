"""The seven reply-pipeline nodes (PRD V7 §5.3):

    ingest -> prefilter -> scout -> token_budget -> strategist -> finalize -> persist_gate

Every node has the signature ``async def node(state, config) -> dict`` --
LangGraph injects ``config`` (see ``backend.pipeline.graph``); nodes read
``config["configurable"]["session_local"]`` / ``["redis_client"]`` for
per-run, non-serializable resources rather than carrying them in ``state``
(which the Postgres checkpointer persists between hops).

Each node opens its own ``async with session_local() as db:`` block(s) --
nodes never hold a session across an ``await`` that yields to another node,
and the strategist node opens a fresh session per concurrent batch (see its
docstring for the regression this pins).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.ingestion.service import BudgetExceededError, ingest_campaign
from backend.ingestion.tokens import NoUsableTokenError
from backend.models import (
    Campaign,
    CampaignStatus,
    DraftReply,
    DraftStatus,
    Organization,
    PlatformEnum,
    PostedHistory,
    ReplyType,
    SubredditSafetyProfile,
    SystemLog,
    TargetAuthor,
)
from backend.pipeline.draft_format import append_disclosure, finalize_draft, mentions_product
from backend.pipeline.llm_transport import DEFAULT_PIPELINE_MODEL, llm_call_kwargs, resolve_model
from backend.pipeline.prefilter import (
    campaign_daily_cap_key,
    matches_keyword_filters,
    reserve_daily_slot,
    subreddit_daily_cap_key,
)
from backend.pipeline.prompt_render import render_angle_template
from backend.pipeline.scout import DEFAULT_SCOUT_INSTRUCTIONS, run_scout
from backend.pipeline.signal_tier import compute_signal_tier
from backend.pipeline.state import PipelineState
from backend.pipeline.strategist import (
    BATCH_CONCURRENCY,
    BATCH_SIZE,
    run_strategist_batch,
    run_strategist_single,
)
from backend.pipeline.templates import get_angle_templates, get_master_context_template, get_top_angles_hint
from backend.utils.cost_guard import CostLimitExceeded, check_and_record_llm_usage
from backend.utils.org_lookups import (
    get_active_apify_vault_tokens,
    get_org_llm_config,
    get_org_persona,
    get_org_settings,
)
from backend.utils.tokenizer import compute_token_budget, count_tokens

logger = logging.getLogger(__name__)


async def _log_system(db, org_id: int, level: str, module: str, message: str) -> None:
    db.add(SystemLog(org_id=org_id, level=level, module=module, message=message))
    await db.flush()


def _subreddit_value(campaign) -> str:
    return str(campaign.value or "").removeprefix("r/").removeprefix("/r/").strip("/")


def _config(cfg: dict) -> dict:
    return cfg.get("configurable", {})


# ---------------------------------------------------------------------------
# 1. ingest
# ---------------------------------------------------------------------------


async def ingest_node(state: PipelineState, config: RunnableConfig) -> dict:
    cfg = _config(config)
    session_local = cfg["session_local"]
    redis_client = cfg.get("redis_client")
    campaign_id = state["campaign_id"]

    async with session_local() as db:
        campaign = await db.get(Campaign, campaign_id)
        if not campaign or campaign.status != CampaignStatus.ACTIVE:
            return {"terminal": True, "terminal_reason": "campaign_inactive_or_missing"}

        org_id = campaign.org_id
        platform_value = getattr(campaign.platform, "value", str(campaign.platform))
        org_settings = await get_org_settings(db, org_id)
        vault_tokens = await get_active_apify_vault_tokens(db, org_id)

        try:
            posts = await ingest_campaign(
                db, campaign, org_settings, vault_tokens, redis_client=redis_client
            )
        except BudgetExceededError as exc:
            await _log_system(db, org_id, "WARNING", "pipeline.ingest", str(exc))
            await db.commit()
            return {
                "org_id": org_id,
                "platform": platform_value,
                "terminal": True,
                "terminal_reason": "SKIPPED_BUDGET",
            }
        except NoUsableTokenError as exc:
            await _log_system(db, org_id, "WARNING", "pipeline.ingest", str(exc))
            await db.commit()
            return {
                "org_id": org_id,
                "platform": platform_value,
                "terminal": True,
                "terminal_reason": "SKIPPED_NO_TOKEN",
            }

        await _log_system(
            db, org_id, "INFO", "pipeline.ingest",
            f"Campaign {campaign_id} ingested {len(posts)} post(s)",
        )
        await db.commit()

    return {"org_id": org_id, "platform": platform_value, "posts": posts}


# ---------------------------------------------------------------------------
# 2. prefilter
# ---------------------------------------------------------------------------


async def prefilter_node(state: PipelineState, config: RunnableConfig) -> dict:
    if state.get("terminal"):
        return {}

    posts = state.get("posts", [])
    dropped = list(state.get("dropped", []))
    if not posts:
        return {"posts": [], "dropped": dropped}

    cfg = _config(config)
    session_local = cfg["session_local"]
    redis_client = cfg.get("redis_client")
    campaign_id = state["campaign_id"]
    org_id = state["org_id"]
    platform = state["platform"]

    async with session_local() as db:
        campaign = await db.get(Campaign, campaign_id)
        keywords = campaign.keywords or []
        post_ids = [p["post_id"] for p in posts]

        posted_ids = set(
            (
                await db.execute(
                    select(PostedHistory.post_id).where(
                        PostedHistory.org_id == org_id,
                        PostedHistory.platform == PlatformEnum(platform),
                        PostedHistory.post_id.in_(post_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_draft_ids = set(
            (
                await db.execute(
                    select(DraftReply.post_id).where(
                        DraftReply.campaign_id == campaign_id,
                        DraftReply.post_id.in_(post_ids),
                    )
                )
            )
            .scalars()
            .all()
        )

        safety_profile = None
        subreddit = None
        if platform == "REDDIT":
            subreddit = _subreddit_value(campaign)
            safety_profile = (
                await db.execute(
                    select(SubredditSafetyProfile).where(
                        SubredditSafetyProfile.org_id == org_id,
                        SubredditSafetyProfile.subreddit == subreddit,
                    )
                )
            ).scalar_one_or_none()

        day = date.today().isoformat()
        campaign_cap_key = campaign_daily_cap_key(campaign_id, day)
        subreddit_cap_key = (
            subreddit_daily_cap_key(org_id, subreddit, day) if safety_profile else None
        )

        survivors = []
        for post in posts:
            pid = post["post_id"]
            if pid in posted_ids:
                dropped.append({"post_id": pid, "reason": "already_posted"})
                continue
            if pid in existing_draft_ids:
                dropped.append({"post_id": pid, "reason": "duplicate_draft"})
                continue

            haystack = f"{post.get('title', '')}\n{post.get('content', '')}"
            passed, _matched = matches_keyword_filters(haystack, keywords)
            if not passed:
                dropped.append({"post_id": pid, "reason": "keyword_filter"})
                continue

            if not await reserve_daily_slot(redis_client, campaign_cap_key, campaign.daily_draft_cap):
                dropped.append({"post_id": pid, "reason": "campaign_daily_cap"})
                continue

            if subreddit_cap_key and not await reserve_daily_slot(
                redis_client, subreddit_cap_key, safety_profile.max_daily_drafts
            ):
                dropped.append({"post_id": pid, "reason": "subreddit_daily_cap"})
                continue

            survivors.append(post)

        for d in dropped:
            await _log_system(
                db, org_id, "INFO", "pipeline.prefilter", f"Dropped {d['post_id']}: {d['reason']}"
            )
        await db.commit()

    return {"posts": survivors, "dropped": dropped}


# ---------------------------------------------------------------------------
# 3. scout
# ---------------------------------------------------------------------------


async def scout_node(state: PipelineState, config: RunnableConfig) -> dict:
    if state.get("terminal"):
        return {}

    posts = state.get("posts", [])
    if not posts:
        return {"selections": []}

    cfg = _config(config)
    session_local = cfg["session_local"]
    org_id = state["org_id"]
    platform = state["platform"]

    async with session_local() as db:
        llm_config = await get_org_llm_config(db, org_id)
        org_settings = await get_org_settings(db, org_id)
        angle_templates = await get_angle_templates(db, org_id, platform)
        hint = await get_top_angles_hint(db, org_id, platform)

        if not llm_config or not llm_config.model_name:
            await _log_system(
                db, org_id, "WARNING", "pipeline.scout", "No LLM configured for org; skipping scout"
            )
            await db.commit()
            return {
                "selections": [],
                "errors": state.get("errors", []) + ["scout: no LLM configured"],
            }

        model = resolve_model(llm_config)
        call_kwargs = llm_call_kwargs(llm_config)
        instructions = (
            org_settings.scout_prompt
            if org_settings and org_settings.scout_prompt
            else DEFAULT_SCOUT_INSTRUCTIONS
        )

        try:
            result = await run_scout(
                posts,
                list(angle_templates.keys()),
                platform=platform,
                model=model,
                call_kwargs=call_kwargs,
                instructions=instructions,
                hint=hint,
            )
        except Exception as exc:  # noqa: BLE001 - any LLM/parse failure degrades to "no selections"
            await _log_system(db, org_id, "ERROR", "pipeline.scout", f"Scout failed: {exc}")
            await db.commit()
            return {"selections": [], "errors": state.get("errors", []) + [f"scout: {exc}"]}

        posts_by_id = {p["post_id"]: p for p in posts}
        dropped = list(state.get("dropped", []))
        valid_selections = []
        for sel in result.selections:
            post = posts_by_id.get(sel.post_id)
            if not post:
                dropped.append({"post_id": sel.post_id, "reason": "scout_selected_unknown_post"})
                continue
            if sel.angle_name not in angle_templates:
                dropped.append(
                    {"post_id": sel.post_id, "reason": f"scout_selected_unknown_angle:{sel.angle_name}"}
                )
                continue

            reply_type = sel.reply_type
            target_comment_id = sel.target_comment_id
            if reply_type == "REPLY_TO_COMMENT":
                comment_ids = {c.get("comment_id") for c in post.get("top_comments", [])}
                if not target_comment_id or target_comment_id not in comment_ids:
                    reply_type = "NEW_COMMENT"
                    target_comment_id = None

            valid_selections.append(
                {
                    "post_id": sel.post_id,
                    "angle_name": sel.angle_name,
                    "reply_type": reply_type,
                    "target_comment_id": target_comment_id,
                    "confidence": sel.confidence,
                    "reasoning": sel.reasoning,
                }
            )

        await _log_system(
            db, org_id, "INFO", "pipeline.scout",
            f"Selected {len(valid_selections)} of {len(posts)} post(s)",
        )
        await db.commit()

    return {"selections": valid_selections, "dropped": dropped}


# ---------------------------------------------------------------------------
# 4. token_budget
# ---------------------------------------------------------------------------


async def token_budget_node(state: PipelineState, config: RunnableConfig) -> dict:
    selections = state.get("selections", [])
    if not selections:
        return {"truncated_content": {}}

    cfg = _config(config)
    session_local = cfg["session_local"]
    org_id = state["org_id"]
    posts_by_id = {p["post_id"]: p for p in state.get("posts", [])}

    async with session_local() as db:
        llm_config = await get_org_llm_config(db, org_id)
        persona = await get_org_persona(db, org_id)

        if not persona:
            return {"truncated_content": {}}

        model = resolve_model(llm_config)

        # Recompute against the model actually in use rather than trusting
        # OrgPersona.master_context_token_count, which is only refreshed on
        # persona save / explicit model-change handlers and can be stale.
        persona_text = (persona.master_context or "") + str(persona.rulesets_dos_donts or "")
        persona.master_context_token_count = count_tokens(model, persona_text)
        budget = compute_token_budget(model, persona)

    truncated: dict[str, dict] = {}
    for sel in selections:
        post = posts_by_id.get(sel["post_id"])
        if not post:
            continue

        content = post.get("content", "")
        comments = list(post.get("top_comments", []))
        removed = 0

        def _rendered_tokens() -> int:
            comment_text = "\n\n".join(c.get("content", "") for c in comments)
            return count_tokens(model, f"{content}\n\n{comment_text}")

        # Oldest comments first: the actor already orders top_comments
        # best/newest-first, so popping off the tail drops the oldest.
        while comments and _rendered_tokens() > budget:
            comments.pop()
            removed += 1

        truncated_flag = removed > 0
        if _rendered_tokens() > budget:
            max_chars = max(500, budget * 4)  # ~4 chars/token, last-resort hard cap
            if len(content) > max_chars:
                content = content[:max_chars]
                truncated_flag = True

        truncated[sel["post_id"]] = {
            "content": content,
            "top_comments": comments,
            "truncated": truncated_flag,
            "removed_comments": removed,
        }

    return {"truncated_content": truncated}


# ---------------------------------------------------------------------------
# 5. strategist
# ---------------------------------------------------------------------------


async def strategist_node(state: PipelineState, config: RunnableConfig) -> dict:
    selections = state.get("selections", [])
    if not selections:
        return {"drafts": []}

    cfg = _config(config)
    session_local = cfg["session_local"]
    campaign_id = state["campaign_id"]
    org_id = state["org_id"]
    platform = state["platform"]
    posts_by_id = {p["post_id"]: p for p in state.get("posts", [])}
    truncated = state.get("truncated_content", {})

    async with session_local() as db:
        campaign = await db.get(Campaign, campaign_id)
        llm_config = await get_org_llm_config(db, org_id)
        persona = await get_org_persona(db, org_id)
        master_context_row = await get_master_context_template(db, org_id, platform)
        angle_templates = await get_angle_templates(db, org_id, platform)

    if not llm_config or not llm_config.model_name:
        return {"drafts": [], "errors": state.get("errors", []) + ["strategist: no LLM configured"]}

    model = resolve_model(llm_config)
    call_kwargs = llm_call_kwargs(llm_config)

    persona_block = ""
    if persona:
        persona_block = (
            f"Rules (Do's & Don'ts): {persona.rulesets_dos_donts or '{}'}\n\n"
            f"Tone Guidelines: {persona.tone_guidelines or ''}"
        )
    base_master_context = master_context_row.content if master_context_row else ""
    combined_master_context = f"{base_master_context}\n\n{persona_block}".strip()

    subreddit = _subreddit_value(campaign) if platform == "REDDIT" else ""

    items = []
    for sel in selections:
        post = posts_by_id.get(sel["post_id"])
        if not post:
            continue

        tc = truncated.get(sel["post_id"], {})
        content = tc.get("content", post.get("content", ""))
        comments = tc.get("top_comments", post.get("top_comments", []))

        target_comment = None
        if sel.get("reply_type") == "REPLY_TO_COMMENT" and sel.get("target_comment_id"):
            target_comment = next(
                (c for c in comments if c.get("comment_id") == sel["target_comment_id"]), None
            )

        angle = angle_templates.get(sel["angle_name"])
        angle_content = angle.content if angle else ""
        angle_version = angle.version if angle else 1

        rendered_prompt = render_angle_template(
            angle_content,
            {
                "MASTER_CONTEXT": combined_master_context,
                "POST_TEXT": content,
                "POST_BODY": content,
                "TWEET_TEXT": content,
                "POST_TITLE": post.get("title", ""),
                "PARENT_COMMENT": target_comment.get("content", "") if target_comment else "",
                "TARGET_COMMENT": target_comment.get("content", "") if target_comment else "",
                "SUBREDDIT": subreddit,
            },
        )

        items.append(
            {
                "post_id": sel["post_id"],
                "angle_name": sel["angle_name"],
                "reply_type": sel.get("reply_type", "NEW_COMMENT"),
                "target_comment_id": sel.get("target_comment_id"),
                "target_comment": target_comment,
                "confidence": sel.get("confidence", 0.0),
                "reasoning": sel.get("reasoning", ""),
                "prompt": rendered_prompt,
                "prompt_template_version": f"{sel['angle_name']}_v{angle_version}",
            }
        )

    if not items:
        return {"drafts": []}

    chunks = [items[i : i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
    sem = asyncio.Semaphore(BATCH_CONCURRENCY)
    all_drafts: list[dict] = []
    drafts_lock = asyncio.Lock()

    async def _draft_batch(chunk: list[dict]) -> None:
        async with sem:
            draft_map = await run_strategist_batch(chunk, model, call_kwargs)

            for item in chunk:
                text = draft_map.get(item["post_id"], "")
                if text and text.strip():
                    continue
                try:
                    draft_map[item["post_id"]] = await run_strategist_single(item, model, call_kwargs)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Strategist fallback failed for %s: %s", item["post_id"], exc)
                    draft_map[item["post_id"]] = ""

            batch_drafts = [
                {
                    **item,
                    "draft_text": draft_map.get(item["post_id"], ""),
                    "model_used": model,
                    "response_token_count": count_tokens(model, draft_map.get(item["post_id"]) or ""),
                }
                for item in chunk
            ]

            # Fresh DB session per concurrent batch: AsyncSession is not safe
            # for concurrent use across gathered coroutines. This is the
            # social-agent regression `test_pipeline_concurrency.py` pins --
            # ported as tests/pipeline/test_strategist_concurrency.py.
            async with session_local() as batch_db:
                plural = "y" if len(chunk) == 1 else "ies"
                await _log_system(
                    batch_db, org_id, "INFO", "pipeline.strategist",
                    f"Drafted {len(chunk)} repl{plural} (batch)",
                )
                await batch_db.commit()

            async with drafts_lock:
                all_drafts.extend(batch_drafts)

    await asyncio.gather(*[_draft_batch(chunk) for chunk in chunks])

    return {"drafts": all_drafts}


# ---------------------------------------------------------------------------
# 6. finalize
# ---------------------------------------------------------------------------


async def finalize_node(state: PipelineState, config: RunnableConfig) -> dict:
    drafts = state.get("drafts", [])
    if not drafts:
        return {"drafts": []}

    cfg = _config(config)
    session_local = cfg["session_local"]
    org_id = state["org_id"]
    platform = state["platform"]

    async with session_local() as db:
        org = await db.get(Organization, org_id)
        org_settings = await get_org_settings(db, org_id)

    hook = org_settings.reply_hook if org_settings else None
    disclosure_on = bool(org_settings.disclosure_reddit) if org_settings else True
    product_name = org.name if org else None

    finalized = []
    for d in drafts:
        text = finalize_draft(d.get("draft_text", ""), hook)
        if platform == "REDDIT" and disclosure_on and mentions_product(text, product_name):
            text = append_disclosure(text, product_name)
        finalized.append({**d, "draft_text": text})

    return {"drafts": finalized}


# ---------------------------------------------------------------------------
# 7. persist_gate
# ---------------------------------------------------------------------------


async def persist_gate_node(state: PipelineState, config: RunnableConfig) -> dict:
    drafts = state.get("drafts", [])
    if not drafts:
        return {"persisted_draft_ids": []}

    cfg = _config(config)
    session_local = cfg["session_local"]
    redis_client = cfg.get("redis_client")
    org_id = state["org_id"]
    campaign_id = state["campaign_id"]
    platform_value = state["platform"]
    posts_by_id = {p["post_id"]: p for p in state.get("posts", [])}

    persisted_ids: list[int] = []

    async with session_local() as db:
        watch_names = list(
            (
                await db.execute(select(TargetAuthor.name).where(TargetAuthor.org_id == org_id))
            )
            .scalars()
            .all()
        )

        for item in drafts:
            post = posts_by_id.get(item["post_id"], {})
            draft_text = item.get("draft_text") or ""
            model_used = item.get("model_used") or DEFAULT_PIPELINE_MODEL

            status = DraftStatus.PENDING
            if not draft_text.strip():
                status = DraftStatus.FAILED
            else:
                estimated_tokens = count_tokens(model_used, (item.get("prompt") or "") + draft_text)
                try:
                    await check_and_record_llm_usage(
                        org_id=org_id,
                        estimated_tokens=estimated_tokens,
                        model=model_used,
                        r=redis_client,
                        db=db,
                    )
                except CostLimitExceeded:
                    status = DraftStatus.FAILED_COST_LIMIT

            tier = compute_signal_tier(post, watch_names)
            reply_type = ReplyType(item.get("reply_type", "NEW_COMMENT"))
            target_comment = None
            if reply_type == ReplyType.REPLY_TO_COMMENT and item.get("target_comment_id"):
                target_comment = next(
                    (
                        c
                        for c in post.get("top_comments", [])
                        if c.get("comment_id") == item["target_comment_id"]
                    ),
                    None,
                )
            reply_target_url = (target_comment.get("url") if target_comment else None) or post.get("url")

            posted_at_source = None
            raw_posted_at = post.get("posted_at")
            if raw_posted_at:
                try:
                    posted_at_source = datetime.fromisoformat(raw_posted_at)
                except (TypeError, ValueError):
                    posted_at_source = None

            row = DraftReply(
                org_id=org_id,
                campaign_id=campaign_id,
                platform=PlatformEnum(platform_value),
                post_id=item["post_id"],
                author=post.get("author"),
                author_name=post.get("author_name"),
                author_headline=post.get("author_headline"),
                author_profile_url=post.get("author_profile_url"),
                title=post.get("title"),
                original_content=post.get("content"),
                top_comments=post.get("top_comments"),
                url=post.get("url"),
                reply_target_url=reply_target_url,
                reply_type=reply_type,
                target_comment_id=item.get("target_comment_id"),
                target_comment_content=target_comment.get("content") if target_comment else None,
                angle_name=item.get("angle_name"),
                ai_draft_text=draft_text,
                status=status,
                confidence=item.get("confidence"),
                triage_reasoning=item.get("reasoning"),
                signal_tier=tier,
                reactions=post.get("reactions", 0) or 0,
                comments_count=post.get("comments", 0) or 0,
                shares=post.get("shares", 0) or 0,
                engagement_score=post.get("engagement_score", 0) or 0,
                posted_at_source=posted_at_source,
                model_used=item.get("model_used"),
                prompt_template_version=item.get("prompt_template_version"),
                prompt_payload={"prompt": item.get("prompt"), "reasoning": item.get("reasoning")},
                response_token_count=item.get("response_token_count"),
            )

            try:
                async with db.begin_nested():
                    db.add(row)
                    await db.flush()
            except IntegrityError:
                # Dedup already ran in prefilter; this is just the final
                # safety net against a race with another concurrent run.
                logger.warning(
                    "Duplicate draft for campaign=%s post=%s dropped at persist_gate",
                    campaign_id, item["post_id"],
                )
                continue
            persisted_ids.append(row.id)

        await _log_system(
            db, org_id, "INFO", "pipeline.persist_gate",
            f"Persisted {len(persisted_ids)} draft(s) for campaign {campaign_id}",
        )
        await db.commit()

    return {"persisted_draft_ids": persisted_ids}
