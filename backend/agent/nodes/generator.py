import os
from sqlalchemy import select
from litellm import acompletion

from backend.database import SessionLocal
from backend.models import (
    Campaign, OrgLLMConfig, OrgPersona, SubredditSafetyProfile,
    DraftStatus, PromptTemplate, PromptType,
)
from backend.utils.celery_async import new_redis_client
from backend.utils.encryption import decrypt
from backend.utils.cost_guard import check_and_record_llm_usage, CostLimitExceeded
from backend.utils.org_lookups import get_org_llm_config, get_org_persona
from backend.utils.tokenizer import count_tokens
from backend.agent.state import AgentState

# The seeded TryEval corpus (backend/prompts/*_v3.md, ported by backend/seed.py)
# uses single-brace ALL_CAPS placeholders inside ANGLE template bodies, e.g.
# {POST_TEXT}, {SUBREDDIT}, {AUTHOR_NAME} -- plus a literal `[MASTER CONTEXT
# BLOCK]` marker (no braces) for where the platform's master-context text
# goes. `_render_angle_template` below is a placeholder-safe str.replace pass
# over these: known placeholders we have real data for get substituted;
# anything else -- including every placeholder we simply don't have data for
# yet (AUTHOR_BIO, HOOK, PILLAR_TAG, ...) -- is left intact rather than
# raising. This is deliberately NOT str.format(): format() requires every
# `{...}` in the string to resolve, so it KeyErrors on all 39 seeded ANGLE
# rows the moment any of these appear.
_MASTER_CONTEXT_MARKER = "[MASTER CONTEXT BLOCK]"


def _render_angle_template(content: str, values: dict) -> str:
    rendered = content
    master_context = values.get("MASTER_CONTEXT")
    if master_context is not None and _MASTER_CONTEXT_MARKER in rendered:
        rendered = rendered.replace(_MASTER_CONTEXT_MARKER, master_context)

    for key, value in values.items():
        if value is None:
            continue
        rendered = rendered.replace("{" + key + "}", str(value))

    return rendered


def _llm_call_kwargs(llm_config: OrgLLMConfig) -> dict:
    kwargs = {}
    if llm_config and llm_config.encrypted_api_key:
        kwargs["api_key"] = decrypt(llm_config.encrypted_api_key, version=llm_config.encrypted_with_key_version)
    elif os.environ.get("OPENROUTER_API_KEY"):
        kwargs["api_key"] = os.environ["OPENROUTER_API_KEY"]

    if llm_config and llm_config.custom_base_url:
        kwargs["api_base"] = llm_config.custom_base_url

    return kwargs


async def draft_generator(state: AgentState) -> AgentState:
    """
    Node 5: DraftGenerator.
    Compiles the final prompt, checks cost limits, and generates the draft.
    """
    campaign_id = state["campaign_id"]
    original_content = state.get("original_content", "")

    # redis.asyncio clients are bound to the event loop that creates them.
    # This node runs inside a Celery task's asyncio.run() call, so the client
    # must be created (and closed) here rather than held at module scope --
    # see backend/utils/celery_async.py.
    async_redis = new_redis_client()
    try:
        async with SessionLocal() as db:
            campaign = await db.get(Campaign, campaign_id)
            llm_config = await get_org_llm_config(db, campaign.org_id)
            persona = await get_org_persona(db, campaign.org_id)

            if not llm_config or not llm_config.model_name or not persona:
                return {**state, "ai_draft_text": "", "final_status": DraftStatus.FAILED}

            model = llm_config.model_name

            # Fetch dynamic prompt template. Priority: org-specific -> system
            # default (org_id IS NULL), matching the campaign's platform when
            # set. Only ANGLE-type rows are eligible here -- MASTER_CONTEXT/
            # SCOUT/ANALYST rows are a different prompt type entirely and must
            # never be selected as the reply prompt.
            stmt = (
                select(PromptTemplate)
                .where(
                    PromptTemplate.type == PromptType.ANGLE,
                    (PromptTemplate.org_id == campaign.org_id) | (PromptTemplate.org_id.is_(None)),
                )
                .where(
                    (PromptTemplate.platform == campaign.platform) | (PromptTemplate.platform.is_(None))
                )
                .order_by(PromptTemplate.org_id.isnot(None).desc())  # org-specific wins over system default
            )
            template_result = await db.execute(stmt)
            prompt_template = template_result.scalars().first()

            master_context = state.get("truncation_details", {}).get(
                "truncated_master_context", persona.master_context or ""
            )

            if not prompt_template:
                system_prompt = (
                    f"Master Context: {master_context}\n\n"
                    f"Rules (Do's & Don'ts): {persona.rulesets_dos_donts}\n\n"
                    f"Tone Guidelines: {persona.tone_guidelines}\n\n"
                    "Generate a helpful and authentic reply to the following content."
                )
                template_version = "legacy_v1"
            else:
                combined_master_context = (
                    f"{master_context}\n\n"
                    f"Rules (Do's & Don'ts): {persona.rulesets_dos_donts or '{}'}\n\n"
                    f"Tone Guidelines: {persona.tone_guidelines or ''}"
                )
                placeholder_values = {
                    "MASTER_CONTEXT": combined_master_context,
                    "POST_TEXT": original_content,
                    "POST_BODY": original_content,
                    "TWEET_TEXT": original_content,
                    "PARENT_COMMENT": state.get("target_comment_content") or "",
                    "TARGET_COMMENT": state.get("target_comment_content") or "",
                    "SUBREDDIT": (campaign.platform_config or {}).get("subreddit", ""),
                }
                system_prompt = _render_angle_template(prompt_template.content, placeholder_values)
                template_version = f"{prompt_template.name}_v{prompt_template.version}"

            estimated_tokens = count_tokens(model, system_prompt + original_content)

            try:
                await check_and_record_llm_usage(
                    org_id=campaign.org_id,
                    estimated_tokens=estimated_tokens,
                    model=model,
                    r=async_redis,
                    db=db,
                )
            except CostLimitExceeded as e:
                return {
                    **state,
                    "ai_draft_text": str(e),
                    "final_status": DraftStatus.FAILED_COST_LIMIT,
                }

            response = await acompletion(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": original_content},
                ],
                **_llm_call_kwargs(llm_config),
            )

            draft_text = response.choices[0].message.content
            token_count = response.usage.total_tokens

            return {
                **state,
                "ai_draft_text": draft_text,
                "response_token_count": token_count,
                "prompt_template_version": template_version,
            }
    finally:
        await async_redis.aclose()


async def confidence_gate(state: AgentState) -> AgentState:
    """
    Node 6: ConfidenceGate.
    V7 has no auto-publish path — every draft is routed to human review
    (HITL inbox). This node tags a signal_tier for triage and always
    finalizes to PENDING (or leaves FAILED_COST_LIMIT / FAILED as-is).
    """
    if state.get("final_status") in (DraftStatus.FAILED, DraftStatus.FAILED_COST_LIMIT):
        return state

    campaign_id = state["campaign_id"]
    confidence = state.get("confidence", 0.0)

    async with SessionLocal() as db:
        campaign = await db.get(Campaign, campaign_id)

        stmt = select(SubredditSafetyProfile).where(
            SubredditSafetyProfile.org_id == campaign.org_id,
            SubredditSafetyProfile.subreddit == campaign.platform_config.get("subreddit")
            if campaign.platform_config else None,
        )
        result = await db.execute(stmt)
        safety_profile = result.scalar_one_or_none()

        if confidence >= 0.8:
            signal_tier = "HIGH"
        elif confidence >= 0.5:
            signal_tier = "MEDIUM"
        else:
            signal_tier = "LOW"

        if safety_profile and safety_profile.require_manual_review:
            signal_tier = f"{signal_tier}_REVIEW_REQUIRED"

        return {
            **state,
            "final_status": DraftStatus.PENDING,
            "signal_tier": signal_tier,
        }
