from litellm import token_counter
import litellm
# Import OrgPersona from models for type hinting
from backend.models import OrgPersona

DEFAULT_MODEL = "openrouter/openai/gpt-4o"  # fallback if org has no LLM configured yet

def count_tokens(model: str, text: str) -> int:
    """
    Counts tokens for a given text using LiteLLM tokenizer for the specific model.
    Encapsulates system message overhead.
    """
    return token_counter(model=model, messages=[{'role': 'system', 'content': text}])

def update_persona_token_counts(
    persona: OrgPersona,
    model: str,           # passed from OrgLLMConfig.model_name at save time
) -> OrgPersona:
    """
    Recalculates the pre-computed token count for the given model.
    Called on: (1) persona save, (2) LLM model change.

    Token counts are model-specific (GPT-4 vs Llama 3). Pre-computing them
    ensures the truncator step is fast. org_personas only carries one
    combined counter (master_context_token_count), covering master_context
    plus rulesets_dos_donts.
    """
    combined_text = (persona.master_context or '') + str(persona.rulesets_dos_donts or '')
    persona.master_context_token_count = count_tokens(model, combined_text)
    return persona

def compute_token_budget(model: str, persona: OrgPersona, safety_reserve: int = 500) -> int:
    """
    Calculates remaining token budget for source-platform content.
    Formula: Max Tokens - (Master Context + Rulesets + Safety Reserve)
    """
    try:
        limit = litellm.get_max_tokens(model)
        # If LiteLLM returns None or something non-integer, use a high-capacity fallback
        if not isinstance(limit, int):
            limit = 16384
    except Exception:
        limit = 16384

    return limit - persona.master_context_token_count - safety_reserve
