import json
import litellm
from litellm import acompletion

from backend.database import SessionLocal
from backend.models import Campaign, OrgLLMConfig, OrgPersona
from backend.utils.encryption import decrypt
from backend.utils.tokenizer import compute_token_budget, count_tokens, DEFAULT_MODEL
from backend.agent.state import AgentState


def _llm_call_kwargs(llm_config: OrgLLMConfig) -> dict:
    """
    Build per-call LiteLLM kwargs from an org's BYOK vault entry. Never mutate
    os.environ — api_key/api_base are always passed per-call. Falls back to
    OPENROUTER_API_KEY from the environment for local/dev orgs with no vault key.
    """
    import os

    kwargs = {}
    if llm_config and llm_config.encrypted_api_key:
        kwargs["api_key"] = decrypt(llm_config.encrypted_api_key, version=llm_config.encrypted_with_key_version)
    elif os.environ.get("OPENROUTER_API_KEY"):
        kwargs["api_key"] = os.environ["OPENROUTER_API_KEY"]

    if llm_config and llm_config.custom_base_url:
        kwargs["api_base"] = llm_config.custom_base_url

    return kwargs


async def llm_intent_classifier(state: AgentState) -> AgentState:
    """
    Node 3: LLMIntentClassifier.
    Uses LiteLLM to evaluate intent. Assigns confidence and triage_reasoning.
    """
    campaign_id = state["campaign_id"]
    original_content = state.get("original_content", "")
    matched_keywords = state.get("matched_keywords", [])

    async with SessionLocal() as db:
        campaign = await db.get(Campaign, campaign_id)
        llm_config = await db.get(OrgLLMConfig, campaign.org_id)

        if not llm_config or not llm_config.model_name:
            return {**state, "confidence": 0.0, "triage_reasoning": "No LLM configuration found"}

        model = llm_config.model_name

        system_prompt = (
            "You are a Triage AI for a DevRel agent. Your goal is to evaluate if a post is relevant "
            "for engagement based on matched keywords and content. "
            "Return a JSON object with 'confidence' (0.0-1.0) and 'reasoning' (brief string)."
        )
        user_prompt = f"Keywords: {matched_keywords}\n\nContent:\n{original_content}"

        response = await acompletion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            **_llm_call_kwargs(llm_config),
        )

        try:
            content = response.choices[0].message.content
            data = json.loads(content)
            confidence = float(data.get("confidence", 0.0))
            reasoning = data.get("reasoning", "No reasoning provided")
        except Exception:
            confidence = 0.0
            reasoning = "Failed to parse LLM response"

        return {
            **state,
            "confidence": confidence,
            "triage_reasoning": reasoning,
        }


async def tokenizer_and_truncator(state: AgentState) -> AgentState:
    """
    Node 4: TokenizerAndTruncator.
    Progressively truncates the oldest comments first if text exceeds budget.
    """
    campaign_id = state["campaign_id"]
    original_content = state.get("original_content", "")

    async with SessionLocal() as db:
        campaign = await db.get(Campaign, campaign_id)
        llm_config = await db.get(OrgLLMConfig, campaign.org_id)
        persona = await db.get(OrgPersona, campaign.org_id)

        model = llm_config.model_name if (llm_config and llm_config.model_name) else DEFAULT_MODEL

        if not persona:
            return {**state, "truncation_applied": False}

        budget = compute_token_budget(model, persona)
        current_tokens = count_tokens(model, original_content)

        if current_tokens <= budget:
            return {**state, "truncation_applied": False}

        parts = original_content.split("\n\n")
        header = parts[:2]
        comments = parts[2:]

        details = {}
        removed_count = 0
        while comments and count_tokens(model, "\n\n".join(header + comments)) > budget:
            comments.pop()
            removed_count += 1

        modified_content = "\n\n".join(header + comments)

        if count_tokens(model, modified_content) > budget:
            details["summarized"] = True
            kwargs = _llm_call_kwargs(llm_config) if llm_config else {}
            if kwargs.get("api_key"):
                try:
                    prompt = f"Summarize this post concisely while keeping core intent to reduce length drastically:\n{modified_content}"
                    response = await acompletion(
                        model=model,
                        messages=[
                            {"role": "system", "content": "You are a concise summarizer."},
                            {"role": "user", "content": prompt},
                        ],
                        **kwargs,
                    )
                    modified_content = response.choices[0].message.content
                except Exception:
                    modified_content = modified_content[:2000]
            else:
                modified_content = modified_content[:2000]

        details["removed_comments"] = removed_count

        return {
            **state,
            "original_content": modified_content,
            "truncation_applied": True,
            "truncation_details": details,
        }
