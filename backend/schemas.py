from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from backend.models import CampaignStatus, DraftStatus, PlatformEnum, ReplyType, PromptType

# ── Org / LLM config ─────────────────────────────────────────────────────────

ALLOWED_LLM_PROVIDERS = {"openrouter", "openai", "anthropic", "gemini", "ollama", "custom"}


class LLMConfigUpdate(BaseModel):
    provider: str = Field(
        default="openrouter",
        description="LLM provider: openrouter (default), openai, anthropic, gemini, ollama, custom",
    )
    model_name: str = Field(..., description="Model name, e.g. openrouter/openai/gpt-4o")
    custom_base_url: Optional[str] = Field(
        None, description="Required when provider == 'custom' (or self-hosted Ollama/vLLM)"
    )
    api_key: Optional[str] = Field(None, description="Plain text API key to be encrypted")
    max_daily_llm_tokens: Optional[int] = None
    max_monthly_llm_cost_usd: Optional[float] = None


class PersonaUpdate(BaseModel):
    master_context: Optional[str] = None
    rulesets_dos_donts: Optional[Dict[str, List[str]]] = None
    tone_guidelines: Optional[str] = None


class PersonaResponse(BaseModel):
    master_context: Optional[str] = None
    rulesets_dos_donts: Optional[Dict[str, List[str]]] = None
    tone_guidelines: Optional[str] = None
    master_context_token_count: int = 0
    model_config = ConfigDict(from_attributes=True)


class SubredditSafetyProfileBase(BaseModel):
    subreddit: str
    max_daily_drafts: int = 3
    require_manual_review: bool = True
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
    timestamp: datetime
    user_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class OrgUsageSchema(BaseModel):
    daily_tokens: int
    monthly_cost_usd: float
    max_daily_tokens: Optional[int]
    max_monthly_cost: Optional[float]


# ── Campaign Schemas ─────────────────────────────────────────────────────────

class CampaignBase(BaseModel):
    platform: PlatformEnum
    name: str
    value: Optional[str] = None
    poll_frequency_minutes: int = 240
    keywords: List[str] = Field(default_factory=list)
    platform_config: Dict[str, Any] = Field(default_factory=dict)
    daily_draft_cap: int = 3


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    value: Optional[str] = None
    status: Optional[CampaignStatus] = None
    poll_frequency_minutes: Optional[int] = None
    keywords: Optional[List[str]] = None
    platform_config: Optional[Dict[str, Any]] = None
    daily_draft_cap: Optional[int] = None


class CampaignResponse(CampaignBase):
    id: int
    org_id: int
    status: CampaignStatus
    created_at: datetime
    updated_at: datetime
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
    platform: PlatformEnum
    posts_tested: int
    results: List[RuleTestResult]


# ── DraftReply Schemas ───────────────────────────────────────────────────────

class DraftReplyResponse(BaseModel):
    id: int
    org_id: int
    campaign_id: int
    platform: PlatformEnum
    post_id: str

    author: Optional[str] = None
    author_name: Optional[str] = None
    author_headline: Optional[str] = None
    author_profile_url: Optional[str] = None

    title: Optional[str] = None
    original_content: Optional[str] = None
    top_comments: Optional[List[Dict[str, Any]]] = None
    url: Optional[str] = None
    reply_target_url: Optional[str] = None

    reply_type: ReplyType
    target_comment_id: Optional[str] = None
    target_comment_content: Optional[str] = None

    angle_name: Optional[str] = None
    ai_draft_text: Optional[str] = None

    status: DraftStatus
    confidence: Optional[float] = None
    triage_reasoning: Optional[str] = None
    signal_tier: Optional[str] = None

    reactions: int = 0
    comments_count: int = 0
    shares: int = 0
    engagement_score: int = 0

    posted_at_source: Optional[datetime] = None
    live_url: Optional[str] = None
    reject_reason: Optional[str] = None

    model_used: Optional[str] = None
    prompt_template_version: Optional[str] = None
    response_token_count: Optional[int] = None

    locked_by_user_id: Optional[int] = None
    locked_at: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DraftEditRequest(BaseModel):
    ai_draft_text: str


class DraftRejectRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class DraftConfirmPostedRequest(BaseModel):
    live_url: Optional[str] = None


class DraftOpenCopyResponse(BaseModel):
    clipboard_text: str
    reply_target_url: Optional[str] = None


class DraftLockResponse(BaseModel):
    status: str
    expires_at: datetime


class DraftReplyListResponse(BaseModel):
    """Paginated envelope for GET /api/inbox/drafts. The frontend contract
    keys on `items`/`total` — keep them stable."""
    items: List[DraftReplyResponse]
    total: int
    page: int
    page_size: int


# ── PromptTemplate Schemas ───────────────────────────────────────────────────

class PromptTemplateBase(BaseModel):
    platform: Optional[PlatformEnum] = None
    type: PromptType
    name: str
    content: str


class PromptTemplateCreate(PromptTemplateBase):
    pass


class PromptTemplateUpdate(BaseModel):
    platform: Optional[PlatformEnum] = None
    type: Optional[PromptType] = None
    name: Optional[str] = None
    content: Optional[str] = None


class PromptTemplateResponse(PromptTemplateBase):
    id: int
    version: int
    org_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


# ── Org Settings ─────────────────────────────────────────────────────────────

class OrgSettingsUpdate(BaseModel):
    reply_hook: Optional[str] = None
    scout_prompt: Optional[str] = None
    linkedin_stale_days: Optional[int] = None
    linkedin_stale_min_engagement: Optional[int] = None
    analyst_enabled: Optional[bool] = None
    disclosure_reddit: Optional[bool] = None
    pillar_taxonomy: Optional[List[Dict[str, str]]] = None
    apify_monthly_budget_usd: Optional[float] = Field(default=None, ge=0)


class OrgSettingsResponse(BaseModel):
    reply_hook: Optional[str] = None
    scout_prompt: Optional[str] = None
    linkedin_stale_days: Optional[int] = None
    linkedin_stale_min_engagement: Optional[int] = None
    analyst_enabled: bool = False
    disclosure_reddit: bool = True
    pillar_taxonomy: Optional[List[Dict[str, str]]] = None
    apify_monthly_budget_usd: float = 50.0
    model_config = ConfigDict(from_attributes=True)


# ── Analyst: TargetAuthor / Competitor ───────────────────────────────────────

class TargetAuthorBase(BaseModel):
    name: str = Field(..., min_length=1)
    tier: Optional[int] = Field(default=None, ge=1, le=3)
    profile_url: Optional[str] = None


class TargetAuthorCreate(TargetAuthorBase):
    pass


class TargetAuthorResponse(TargetAuthorBase):
    id: int
    org_id: int
    model_config = ConfigDict(from_attributes=True)


class CompetitorBase(BaseModel):
    name: str = Field(..., min_length=1)
    platform: Optional[PlatformEnum] = None
    url: Optional[str] = None


class CompetitorCreate(CompetitorBase):
    pass


class CompetitorResponse(CompetitorBase):
    id: int
    org_id: int
    model_config = ConfigDict(from_attributes=True)


# ── Analyst: runs / briefs ────────────────────────────────────────────────────

class AnalystRunResponse(BaseModel):
    run_id: Optional[int] = None
    status: str
    week_of: Optional[date] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class IntelBriefSummary(BaseModel):
    id: int
    org_id: int
    week_of: date
    model_config = ConfigDict(from_attributes=True)


class IntelBriefDetail(IntelBriefSummary):
    content_md: str
