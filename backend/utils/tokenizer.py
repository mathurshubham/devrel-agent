from litellm import token_counter
import litellm
# Import OrgPersona from models for type hinting
from backend.models import OrgPersona

DEFAULT_MODEL = "gpt-4o"  # fallback if org has no LLM configured yet

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
    Recalculates pre-computed token counts for the given model.
    Called on: (1) persona save, (2) LLM model change.
    
    Teammate 1: Token counts are model-specific (GPT-4 vs Llama 3). 
    Pre-computing them ensures Node 4 (Truncator) is fast.
    """
    persona.master_context_tokens = count_tokens(model, persona.master_context or '')
    persona.rulesets_token_count  = count_tokens(model, str(persona.rulesets_dos_donts or ''))
    return persona

def compute_token_budget(model: str, persona: OrgPersona, safety_reserve: int = 500) -> int:
    """
    Calculates remaining token budget for Reddit posts/comments.
    Formula: Max Tokens - (Master Context + Rulesets + Safety Reserve)
    """
    try:
        limit = litellm.get_max_tokens(model)
        # If LiteLLM returns None or something non-integer, use your high-capacity fallback
        if not isinstance(limit, int):
            limit = 16384 
    except Exception:
        limit = 16384
        
    return limit - persona.master_context_tokens - persona.rulesets_token_count - safety_reserve
