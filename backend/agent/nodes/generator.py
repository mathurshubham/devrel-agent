import os
import redis.asyncio as redis
from sqlalchemy import select
from litellm import acompletion

from backend.database import SessionLocal
from backend.models import (
    Campaign, OrgLLMConfig, OrgPersona, SubredditSafetyProfile,
    DraftStatus, PromptTemplate,
)
from backend.utils.encryption import decrypt
from backend.utils.cost_guard import check_and_record_llm_usage, CostLimitExceeded
from backend.utils.tokenizer import count_tokens
from backend.agent.state import AgentState

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
async_redis = redis.from_url(REDIS_URL)


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

    async with SessionLocal() as db:
        campaign = await db.get(Campaign, campaign_id)
        llm_config = await db.get(OrgLLMConfig, campaign.org_id)
        persona = await db.get(OrgPersona, campaign.org_id)

        if not llm_config or not llm_config.model_name or not persona:
            return {**state, "ai_draft_text": "", "final_status": DraftStatus.FAILED}

        model = llm_config.model_name

        # Fetch dynamic prompt template. Priority: org-specific -> system default
        # (org_id IS NULL), matching the campaign's platform when set.
        stmt = (
            select(PromptTemplate)
            .where(
                (PromptTemplate.org_id == campaign.org_id) | (PromptTemplate.org_id.is_(None)),
            )
            .where(
                (PromptTemplate.platform == campaign.platform) | (PromptTemplate.platform.is_(None))
            )
            .order_by(PromptTemplate.org_id.isnot(None).desc())  # org-specific wins over system default
        )
        template_result = await db.execute(stmt)
        prompt_template = template_result.scalars().first()

        if not prompt_template:
            system_prompt = (
                f"Master Context: {persona.master_context}\n\n"
                f"Rules (Do's & Don'ts): {persona.rulesets_dos_donts}\n\n"
                f"Tone Guidelines: {persona.tone_guidelines}\n\n"
                "Generate a helpful and authentic reply to the following content."
            )
            template_version = "legacy_v1"
        else:
            master_context = state.get("truncation_details", {}).get(
                "truncated_master_context", persona.master_context or ""
            )
            system_prompt = prompt_template.content.format(
                master_context=master_context,
                rulesets_dos_donts=persona.rulesets_dos_donts or "{}",
                tone_guidelines=persona.tone_guidelines or "",
            )
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
