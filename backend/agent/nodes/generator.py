import os
import redis.asyncio as redis
from datetime import date
from sqlalchemy.future import select
from litellm import completion
from backend.database import SessionLocal
from backend.models import Campaign, OrgLLMConfig, OrgPersona, SubredditSafetyProfile, DraftStatus
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

        # Build prompt from persona
        system_prompt = (
            f"Master Context: {persona.master_context}\n\n"
            f"Rules (Do's & Don'ts): {persona.rulesets_dos_donts}\n\n"
            f"Tone Guidelines: {persona.tone_guidelines}\n\n"
            "Generate a helpful and authentic Reddit reply to the following content."
        )
        
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
            "model_payload_token_count": token_count
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
        result = await db.execute(
            select(SubredditSafetyProfile).where(
                SubredditSafetyProfile.org_id == campaign.org_id,
                SubredditSafetyProfile.subreddit_name == campaign.subreddit_name
            )
        )
        safety_profile = result.scalar_one_or_none()
        
        allow_auto = campaign.is_auto_pilot_enabled
        if safety_profile:
            if not safety_profile.allow_auto_pilot:
                allow_auto = False
            # We could also check max_daily_posts here if needed
            
        threshold = campaign.auto_pilot_confidence_threshold
        
        # Check Redis counter for autopilot limit
        today = date.today().isoformat()
        auto_key = f"autopilot:count:{campaign_id}:{today}"
        auto_count_raw = await async_redis.get(auto_key)
        auto_count = int(auto_count_raw or 0)
        
        is_eligible = (
            confidence >= threshold and
            allow_auto and
            auto_count < campaign.auto_pilot_daily_limit
        )
        
        final_status = DraftStatus.PUBLISHED if is_eligible else DraftStatus.PENDING
        
        # If published, increment Redis counter
        if final_status == DraftStatus.PUBLISHED:
            await async_redis.incr(auto_key)
            # Set expiry if new key
            if auto_count == 0:
                await async_redis.expire(auto_key, 86400) # 24h
                
        return {
            **state,
            "final_status": final_status
        }
