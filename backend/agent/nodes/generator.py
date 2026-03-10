import os
import redis.asyncio as redis
from datetime import date
from sqlalchemy.future import select
from litellm import completion
from backend.database import SessionLocal
from backend.models import (
    Campaign, OrgLLMConfig, OrgPersona, SubredditSafetyProfile, 
    DraftStatus, PromptTemplate
)
from backend.utils.encryption import decrypt
from backend.utils.cost_guard import check_and_record_llm_usage
from backend.utils.tokenizer import count_tokens
from backend.agent.state import AgentState

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# Use async redis client to match cost_guard.py requirements
async_redis = redis.from_url(REDIS_URL)

async def draft_generator(state: AgentState) -> AgentState:
    """
    Node 5: DraftGenerator
    Compiles final prompt, checks cost limits, and generates the draft.
    """
    campaign_id = state["campaign_id"]
    original_text = state.get("original_text", "")
    
    async with SessionLocal() as db:
        campaign = await db.get(Campaign, campaign_id)
        llm_config = await db.get(OrgLLMConfig, campaign.org_id)
        persona = await db.get(OrgPersona, campaign.org_id)
        
        if not llm_config or not persona:
            return {**state, "ai_draft_text": "", "final_status": DraftStatus.FAILED}

        model = llm_config.model_name
        api_key = decrypt(llm_config.encrypted_api_key) if llm_config.encrypted_api_key else None

        # Fetch Dynamic Prompt Template (TRD Section 5.3)
        # Priority: Org-specific Template -> System Default Template
        stmt = select(PromptTemplate).where(
            (PromptTemplate.org_id == campaign.org_id) | (PromptTemplate.is_system_default == True)
        ).order_by(PromptTemplate.org_id.desc()) # Custom org template first if it exists
        
        template_result = await db.execute(stmt)
        prompt_template = template_result.scalars().first()
        
        if not prompt_template:
             # Fallback if no template found (should not happen with system defaults)
             system_prompt = (
                f"Master Context: {persona.master_context}\n\n"
                f"Rules (Do's & Don'ts): {persona.rulesets_dos_donts}\n\n"
                f"Tone Guidelines: {persona.tone_guidelines}\n\n"
                "Generate a helpful and authentic Reddit reply to the following content."
            )
             template_version = "legacy_v1"
        else:
            # Inject Variables into Prompt Template
            system_prompt = prompt_template.prompt_body.format(
                master_context=persona.master_context or "",
                rulesets_dos_donts=persona.rulesets_dos_donts or "{}",
                tone_guidelines=persona.tone_guidelines or ""
            )
            template_version = f"{prompt_template.title}_v{prompt_template.version}"

        # Estimate tokens for cost guard
        estimated_tokens = count_tokens(model, system_prompt + original_text)
        
        # Check and record usage
        try:
            await check_and_record_llm_usage(
                org_id=campaign.org_id,
                estimated_tokens=estimated_tokens,
                model=model,
                r=async_redis,
                db=db
            )
        except Exception as e:
            return {
                **state, 
                "ai_draft_text": str(e), 
                "final_status": DraftStatus.FAILED_COST_LIMIT
            }

        response = completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": original_text}
            ],
            api_key=api_key
        )

        draft_text = response.choices[0].message.content
        token_count = response.usage.total_tokens
        
        return {
            **state,
            "ai_draft_text": draft_text,
            "model_payload_token_count": token_count,
            "prompt_template_version": template_version
        }

async def confidence_gate(state: AgentState) -> AgentState:
    """
    Node 6: ConfidenceGate
    Routes to PUBLISHED or PENDING based on confidence and safety profiles.
    """
    campaign_id = state["campaign_id"]
    confidence = state.get("confidence_score", 0.0)
    
    async with SessionLocal() as db:
        campaign = await db.get(Campaign, campaign_id)
        
        # Check Subreddit Safety Profile
        stmt = select(SubredditSafetyProfile).where(
            SubredditSafetyProfile.org_id == campaign.org_id,
            SubredditSafetyProfile.subreddit_name == campaign.subreddit_name
        )
        result = await db.execute(stmt)
        safety_profile = result.scalar_one_or_none()
        
        allow_auto = campaign.is_auto_pilot_enabled
        daily_limit = campaign.auto_pilot_daily_limit
        threshold = campaign.auto_pilot_confidence_threshold

        if safety_profile:
            # Profile overrides: disabling auto-pilot or requiring manual review
            if not safety_profile.allow_auto_pilot or safety_profile.require_manual_review:
                allow_auto = False
            
            # Subreddit-level post limit (per org)
            daily_limit = min(daily_limit, safety_profile.max_daily_posts)
            
        # Check Redis counters
        today = date.today().isoformat()
        
        # 1. Campaign-level counter
        campaign_key = f"autopilot:count:campaign:{campaign_id}:{today}"
        campaign_count = int(await async_redis.get(campaign_key) or 0)
        
        # 2. Subreddit-level counter (enforced by Safety Profile)
        subreddit_key = f"autopilot:count:subreddit:{campaign.org_id}:{campaign.subreddit_name}:{today}"
        subreddit_count = int(await async_redis.get(subreddit_key) or 0)
        
        is_eligible = (
            confidence >= threshold and
            allow_auto and
            campaign_count < campaign.auto_pilot_daily_limit and
            subreddit_count < daily_limit
        )
        
        final_status = DraftStatus.PUBLISHED if is_eligible else DraftStatus.PENDING
        
        # If published, increment Redis counters
        if final_status == DraftStatus.PUBLISHED:
            # Increment campaign counter
            await async_redis.incr(campaign_key)
            if campaign_count == 0:
                await async_redis.expire(campaign_key, 86400)
            
            # Increment subreddit counter
            await async_redis.incr(subreddit_key)
            if subreddit_count == 0:
                await async_redis.expire(subreddit_key, 86400)
                
        return {
            **state,
            "final_status": final_status
        }
