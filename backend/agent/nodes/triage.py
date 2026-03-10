import json
import litellm
from litellm import acompletion
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

        response = await acompletion(
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

        parts = original_text.split("\n\n")
        header = parts[:2]
        comments = parts[2:]
        
        details = {}
        api_key = decrypt(llm_config.encrypted_api_key) if llm_config and llm_config.encrypted_api_key else None
        
        removed_count = 0
        while comments and count_tokens(model, "\n\n".join(header + comments)) > budget:
            comments.pop()
            removed_count += 1
            
        modified_text = "\n\n".join(header + comments)
        
        if count_tokens(model, modified_text) > budget:
            details["summarized"] = True
            if api_key:
                try:
                    prompt = f"Summarize this Reddit post concisely while keeping core intent to reduce length drastically:\n{modified_text}"
                    response = await acompletion(
                        model=model,
                        messages=[{"role": "system", "content": "You are a concise summarizer."}, {"role": "user", "content": prompt}],
                        api_key=api_key
                    )
                    modified_text = response.choices[0].message.content
                except Exception:
                    modified_text = modified_text[:2000]
            else:
                modified_text = modified_text[:2000]
                
        # 3. Truncate Master Context tail if still over limit
        current_t = count_tokens(model, modified_text)
        limit = litellm.get_max_tokens(model)
        available_for_master = limit - persona.rulesets_token_count - current_t - 500
        
        if available_for_master < persona.master_context_tokens:
            master = persona.master_context or ""
            char_limit = max(0, int(available_for_master * 3.5))
            details["master_context_truncated"] = True
            details["truncated_master_context"] = master[:char_limit] + "... (truncated due to context limit)"
            
        details["removed_comments"] = removed_count
        
        return {
            **state,
            "original_text": modified_text,
            "truncation_applied": True,
            "truncation_details": details
        }
