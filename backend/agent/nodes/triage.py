import json
import litellm
from litellm import completion
from backend.database import SessionLocal
from backend.models import Campaign, OrgLLMConfig, OrgPersona
from backend.utils.encryption import decrypt
from backend.utils.tokenizer import compute_token_budget, count_tokens
from backend.agent.state import AgentState

async def llm_intent_classifier(state: AgentState) -> AgentState:
    """
    Node 3: LLMIntentClassifier
    Uses LiteLLM to evaluate intent. Assigns confidence_score and triage_reasoning.
    """
    campaign_id = state["campaign_id"]
    original_text = state.get("original_text", "")
    matched_keywords = state.get("matched_keywords", [])

    async with SessionLocal() as db:
        campaign = await db.get(Campaign, campaign_id)
        llm_config = await db.get(OrgLLMConfig, campaign.org_id)
        
        if not llm_config:
            # Fallback or error
            return {**state, "confidence_score": 0.0, "triage_reasoning": "No LLM configuration found"}

        model = llm_config.model_name
        api_key = decrypt(llm_config.encrypted_api_key) if llm_config.encrypted_api_key else None

        system_prompt = (
            "You are a Triage AI for a DevRel agent. Your goal is to evaluate if a Reddit post is relevant "
            "for engagement based on matched keywords and content. "
            "Return a JSON object with 'confidence_score' (0.0-1.0) and 'reasoning' (brief string)."
        )
        user_prompt = f"Keywords: {matched_keywords}\n\nContent:\n{original_text}"

        response = completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            api_key=api_key,
            response_format={"type": "json_object"}
        )

        try:
            content = response.choices[0].message.content
            data = json.loads(content)
            confidence = float(data.get("confidence_score", 0.0))
            reasoning = data.get("reasoning", "No reasoning provided")
        except Exception:
            confidence = 0.0
            reasoning = "Failed to parse LLM response"

        return {
            **state,
            "confidence_score": confidence,
            "triage_reasoning": reasoning
        }

async def tokenizer_and_truncator(state: AgentState) -> AgentState:
    """
    Node 4: TokenizerAndTruncator
    Progressively truncates the oldest comments first if text exceeds budget.
    """
    campaign_id = state["campaign_id"]
    original_text = state.get("original_text", "")
    
    async with SessionLocal() as db:
        campaign = await db.get(Campaign, campaign_id)
        llm_config = await db.get(OrgLLMConfig, campaign.org_id)
        persona = await db.get(OrgPersona, campaign.org_id)
        
        model = llm_config.model_name if llm_config else "gpt-4o"
        
        if not persona:
            # Should not happen if Phase 3 guards work, but for safety:
            return state

        budget = compute_token_budget(model, persona)
        current_tokens = count_tokens(model, original_text)
        
        if current_tokens <= budget:
            return {**state, "truncation_applied": False}

        # Truncation logic: Split by double newline (our part separator)
        parts = original_text.split("\n\n")
        # Keep Title and Content (first two parts)
        header = parts[:2]
        comments = parts[2:]
        
        removed_count = 0
        while comments and count_tokens(model, "\n\n".join(header + comments)) > budget:
            comments.pop() # Remove last (oldest as per our list build)
            removed_count += 1
            
        truncated_text = "\n\n".join(header + comments)
        
        return {
            **state,
            "original_text": truncated_text,
            "truncation_applied": removed_count > 0,
            "truncation_details": {"removed_comments": removed_count}
        }
