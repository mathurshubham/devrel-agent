from pydantic import BaseModel, Field
from typing import Optional, List, Dict

class LLMConfigUpdate(BaseModel):
    provider: str = Field(..., description="LLM provider: openai, anthropic, gemini, openrouter, ollama")
    model_name: str = Field(..., description="Model name: gpt-4o, claude-3.5-sonnet, openrouter/..., etc.")
    custom_base_url: Optional[str] = None
    api_key: Optional[str] = Field(None, description="Plain text API key to be encrypted")
    max_daily_llm_tokens: Optional[int] = None
    max_monthly_llm_cost_usd: Optional[float] = None

class PersonaUpdate(BaseModel):
    master_context: Optional[str] = None
    rulesets_dos_donts: Optional[Dict[str, List[str]]] = None
    tone_guidelines: Optional[str] = None

class RedditAccountUpdate(BaseModel):
    username: str
    client_id: str
    client_secret: str
    refresh_token: Optional[str] = None
    # Password flow fallback (if no refresh token)
    password: Optional[str] = None
