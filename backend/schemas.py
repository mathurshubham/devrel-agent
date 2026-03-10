from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from backend.models import CampaignStatus, DraftStatus

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

# ── Campaign Schemas ─────────────────────────────────────────────────────────

class CampaignBase(BaseModel):
    name: str
    subreddit_name: str
    keywords: List[str]
    poll_frequency_minutes: int = 240
    comment_fetch_limit: int = 10
    post_fetch_limit: int = 10
    include_op_context: bool = True
    max_comment_chars: int = 500
    is_auto_pilot_enabled: bool = False
    auto_pilot_confidence_threshold: float = 0.95
    auto_pilot_daily_limit: int = 3

class CampaignCreate(CampaignBase):
    pass

class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    subreddit_name: Optional[str] = None
    keywords: Optional[List[str]] = None
    status: Optional[CampaignStatus] = None
    poll_frequency_minutes: Optional[int] = None
    comment_fetch_limit: Optional[int] = None
    post_fetch_limit: Optional[int] = None
    include_op_context: Optional[bool] = None
    max_comment_chars: Optional[int] = None
    is_auto_pilot_enabled: Optional[bool] = None
    auto_pilot_confidence_threshold: Optional[float] = None
    auto_pilot_daily_limit: Optional[int] = None

class CampaignResponse(CampaignBase):
    id: int
    org_id: int
    status: CampaignStatus
    created_at: datetime
    last_polled_at: Optional[datetime] = None
    last_auto_post_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class RuleTestRequest(BaseModel):
    sample_text: str

class RuleTestResult(BaseModel):
    post_title: str
    post_url: str
    matched_keywords: List[str]
    confidence_score: float
    would_trigger: bool
    safety_override: bool
    triage_reasoning: str

class RuleTestResponse(BaseModel):
    tested_at: datetime
    subreddit: str
    posts_tested: int
    results: List[RuleTestResult]

# ── DraftReply Schemas ───────────────────────────────────────────────────────

class DraftReplyResponse(BaseModel):
    id: int
    campaign_id: int
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
    
    reddit_post_id: str
    reddit_post_url: str
    original_text: str
    
    ai_draft_text: str
    confidence_score: float
    model_used: Optional[str] = None
    prompt_template_version: Optional[str] = None
    
    truncation_applied: bool
    status: DraftStatus
    locked_by_user_id: Optional[int] = None
    locked_at: Optional[datetime] = None
    
    live_reddit_url: Optional[str] = None
    failed_reason: Optional[str] = None
    is_auto_pilot_published: bool = False
    
    # TRD V6: Meta for UI Popover
    triage_reasoning: Optional[str] = None # We'll extract this from prompt_payload if needed
    
    model_config = ConfigDict(from_attributes=True)

# ── PromptTemplate Schemas ───────────────────────────────────────────────────

class PromptTemplateBase(BaseModel):
    title: str
    description: str
    category: str
    prompt_body: str

class PromptTemplateCreate(PromptTemplateBase):
    pass

class PromptTemplateUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    prompt_body: Optional[str] = None
    version: Optional[int] = None

class PromptTemplateResponse(PromptTemplateBase):
    id: int
    version: int
    is_system_default: bool
    org_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)

