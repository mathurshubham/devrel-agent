from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict
from datetime import datetime

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

class SubredditSafetyProfileBase(BaseModel):
    subreddit_name: str
    allow_auto_pilot: bool = True
    max_daily_posts: int = 5
    require_manual_review: bool = False
    notes: Optional[str] = None

class SubredditSafetyProfileCreate(SubredditSafetyProfileBase):
    pass

class SubredditSafetyProfileSchema(SubredditSafetyProfileBase):
    id: int
    org_id: int
    model_config = ConfigDict(from_attributes=True)

class AuditLogSchema(BaseModel):
    id: int
    action: str
    details: Optional[Dict] = None
    created_at: datetime
    user_id: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class OrgUsageSchema(BaseModel):
    daily_tokens: int
    monthly_cost_usd: float
    max_daily_tokens: Optional[int]
    max_monthly_cost: Optional[float]

