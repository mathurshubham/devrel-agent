import enum
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (String, Boolean, Integer, ForeignKey, DateTime,
                        Text, Float, UniqueConstraint, Index, Numeric)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

def now_utc():
    return datetime.now(timezone.utc)


# ── Enums ─────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"           # Platform-level operator
    ADMIN       = "ADMIN"                 # Org-level admin
    MEMBER      = "MEMBER"                # Org-level member

class DraftStatus(str, enum.Enum):
    PENDING               = "PENDING"
    APPROVED              = "APPROVED"
    REJECTED              = "REJECTED"
    PUBLISHED             = "PUBLISHED"
    FAILED                = "FAILED"
    DELETED_BY_KILLSWITCH = "DELETED_BY_KILLSWITCH"
    FAILED_COST_LIMIT     = "FAILED_COST_LIMIT"      # NEW V6: LLM cost limit exceeded

class CampaignStatus(str, enum.Enum):
    ACTIVE   = "ACTIVE"
    PAUSED   = "PAUSED"
    ARCHIVED = "ARCHIVED"


# ── ProcessedWebhookEvent ─────────────────────────────────────────────────────

class ProcessedWebhookEvent(Base):
    """
    Clerk webhook idempotency table.
    - ON CONFLICT DO NOTHING used instead of raw try/except (Teammate 3).
    - Rows purged after 30 days by maintenance cron.
    - Replay attack guard is applied BEFORE this lookup (svix-timestamp > 5 min → reject).
    """
    __tablename__ = "processed_webhook_events"

    id           : Mapped[int]      = mapped_column(primary_key=True)
    event_id     : Mapped[str]      = mapped_column(String(255), unique=True, index=True)
    event_type   : Mapped[str]      = mapped_column(String(100))
    processed_at : Mapped[datetime] = mapped_column(default=now_utc)


# ── Organization ──────────────────────────────────────────────────────────────

class Organization(Base):
    __tablename__ = "organizations"

    id           : Mapped[int]      = mapped_column(primary_key=True)
    clerk_org_id : Mapped[str]      = mapped_column(String(255), unique=True, index=True)
    name         : Mapped[str]      = mapped_column(String(255), nullable=False)
    is_active    : Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at   : Mapped[datetime] = mapped_column(default=now_utc)

    users           : Mapped[List["User"]]                   = relationship(back_populates="organization")
    reddit_accounts : Mapped[List["RedditAccount"]]          = relationship(back_populates="organization")
    campaigns       : Mapped[List["Campaign"]]               = relationship(back_populates="organization")
    safety_profiles : Mapped[List["SubredditSafetyProfile"]] = relationship(back_populates="organization")
    llm_config      : Mapped[Optional["OrgLLMConfig"]]       = relationship(back_populates="organization")
    persona         : Mapped[Optional["OrgPersona"]]         = relationship(back_populates="organization")
    audit_logs      : Mapped[List["AuditLog"]]               = relationship(back_populates="organization")


# ── OrgLLMConfig — BYOK LLM Vault ────────────────────────────────────────────

class OrgLLMConfig(Base):
    """BYOK vault for LLM credentials. One record per org."""
    __tablename__ = "org_llm_configs"

    id     : Mapped[int] = mapped_column(primary_key=True)
    org_id : Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True)

    provider                   : Mapped[str]           = mapped_column(String(50))     # 'openai','anthropic','gemini','ollama'
    model_name                 : Mapped[str]           = mapped_column(String(100))    # 'gpt-4o','claude-3-5-sonnet-20241022'
    custom_base_url            : Mapped[Optional[str]] = mapped_column(String(500))    # Ollama/vLLM base URL
    encrypted_api_key          : Mapped[Optional[str]] = mapped_column(Text)           # Fernet token — Text avoids truncation
    encrypted_with_key_version : Mapped[int]           = mapped_column(Integer, default=1)

    # Cost protection (NEW V6)
    max_daily_llm_tokens      : Mapped[Optional[int]]   = mapped_column(Integer)       # Daily token cap across all drafts
    max_monthly_llm_cost_usd  : Mapped[Optional[float]] = mapped_column(Numeric(10,4)) # Monthly USD cost cap

    organization: Mapped["Organization"] = relationship(back_populates="llm_config")


# ── OrgPersona — Context Engine ───────────────────────────────────────────────

class OrgPersona(Base):
    """
    Structured brand identity.
    Pre-computed token counts are model-specific (Teammate 1).
    They are recalculated:
      (1) When the persona is saved.
      (2) When OrgLLMConfig.model_name changes.
    If no LLM is configured yet, counts use DEFAULT_MODEL ('gpt-4o') as fallback.
    """
    __tablename__ = "org_personas"

    id     : Mapped[int] = mapped_column(primary_key=True)
    org_id : Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True)

    master_context        : Mapped[Optional[str]]  = mapped_column(Text)
    master_context_tokens : Mapped[int]            = mapped_column(Integer, default=0)   # Pre-computed, model-specific
    rulesets_dos_donts    : Mapped[Optional[dict]] = mapped_column(JSONB)                # {"dos":[...],"donts":[...]}
    rulesets_token_count  : Mapped[int]            = mapped_column(Integer, default=0)   # Pre-computed, model-specific
    tone_guidelines       : Mapped[Optional[str]]  = mapped_column(Text)

    updated_at: Mapped[datetime] = mapped_column(default=now_utc, onupdate=now_utc)

    organization: Mapped["Organization"] = relationship(back_populates="persona")

    __table_args__ = (
        Index("idx_orgpersona_rulesets_gin", "rulesets_dos_donts", postgresql_using="gin"),
    )


# ── User — Clerk-synced ───────────────────────────────────────────────────────

class User(Base):
    """
    No hashed_password. No UserInvitation table.
    Auth is fully managed by Clerk.
    Invitations managed via Clerk organization.inviteMember() API.
    """
    __tablename__ = "users"

    id                 : Mapped[int]               = mapped_column(primary_key=True)
    clerk_id           : Mapped[str]               = mapped_column(String(255), unique=True, index=True)
    email              : Mapped[str]               = mapped_column(String(255), unique=True, index=True)
    role               : Mapped[UserRole]          = mapped_column(default=UserRole.MEMBER)
    is_active          : Mapped[bool]              = mapped_column(Boolean, default=True)
    created_at         : Mapped[datetime]          = mapped_column(default=now_utc)
    last_login_at      : Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True))
    invited_by_user_id : Mapped[Optional[int]]     = mapped_column(ForeignKey("users.id"))

    org_id      : Mapped[Optional[int]]     = mapped_column(ForeignKey("organizations.id"), nullable=True)
    organization: Mapped[Optional["Organization"]] = relationship(back_populates="users")


# ── RedditAccount — PRAW Vault ────────────────────────────────────────────────

class RedditAccount(Base):
    """
    PRAW credentials vault.
    encrypted_secret is Text (Teammate 3: aligned with OrgLLMConfig.encrypted_api_key).
    Live rate-limit counter in Redis: praw:posts:{id}:{YYYY-MM-DD} TTL=86400s.
    """
    __tablename__ = "reddit_accounts"

    id               : Mapped[int] = mapped_column(primary_key=True)
    org_id           : Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    added_by_user_id : Mapped[int] = mapped_column(ForeignKey("users.id"))

    username                   : Mapped[str]  = mapped_column(String(100), nullable=False)
    client_id                  : Mapped[str]  = mapped_column(String(255), nullable=False)
    encrypted_secret           : Mapped[str]  = mapped_column(Text, nullable=False)         # Text — not String(500)
    encrypted_refresh_token    : Mapped[Optional[str]] = mapped_column(Text) # NEW: Long-lived OAuth refresh token
    encrypted_with_key_version : Mapped[int]  = mapped_column(Integer, default=1)

    is_shared_with_team : Mapped[bool]              = mapped_column(Boolean, default=True)
    is_active           : Mapped[bool]              = mapped_column(Boolean, default=True)
    deleted_at          : Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True)) # Soft delete

    # Rate limiting display state (live counter is in Redis)
    last_used_at        : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rate_limit_reset_at : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    organization: Mapped["Organization"] = relationship(back_populates="reddit_accounts")

    __table_args__ = (
        # Partial index: only active accounts (Teammate 2)
        Index("idx_reddit_account_active", "org_id",
              postgresql_where="is_active = true AND deleted_at IS NULL"),
    )


# ── SubredditSafetyProfile ────────────────────────────────────────────────────

class SubredditSafetyProfile(Base):
    """Per-org safety overrides. Checked at LangGraph ConfidenceGate (Node 6)."""
    __tablename__ = "subreddit_safety_profiles"

    id             : Mapped[int]          = mapped_column(primary_key=True)
    org_id         : Mapped[int]          = mapped_column(ForeignKey("organizations.id"))
    subreddit_name : Mapped[str]          = mapped_column(String(100), nullable=False)

    allow_auto_pilot      : Mapped[bool]          = mapped_column(Boolean, default=True)
    max_daily_posts       : Mapped[int]           = mapped_column(Integer, default=3)
    require_manual_review : Mapped[bool]          = mapped_column(Boolean, default=False)
    notes                 : Mapped[Optional[str]] = mapped_column(Text)

    organization: Mapped["Organization"] = relationship(back_populates="safety_profiles")

    __table_args__ = (
        UniqueConstraint("org_id", "subreddit_name", name="uq_org_subreddit_safety"),
    )


# ── Campaign ──────────────────────────────────────────────────────────────────

class Campaign(Base):
    __tablename__ = "campaigns"

    id     : Mapped[int] = mapped_column(primary_key=True)
    org_id : Mapped[int] = mapped_column(ForeignKey("organizations.id"))

    name           : Mapped[str]  = mapped_column(String(255), nullable=False)
    subreddit_name : Mapped[str]  = mapped_column(String(100), index=True)
    # Keywords support exact substring (default) and regex (prefix with "regex:") (Teammate 3)
    keywords       : Mapped[list] = mapped_column(JSONB, nullable=False)

    status     : Mapped[CampaignStatus] = mapped_column(default=CampaignStatus.ACTIVE, index=True)
    created_at : Mapped[datetime]       = mapped_column(default=now_utc)

    # Scheduling — actual dispatch managed by Redis ZSET priority queue (§4.10)
    poll_frequency_minutes : Mapped[int]               = mapped_column(Integer, default=240)
    last_polled_at         : Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True))

    # Comment depth configuration
    comment_fetch_limit : Mapped[int]  = mapped_column(Integer, default=10)
    post_fetch_limit    : Mapped[int]  = mapped_column(Integer, default=10) # NEW: Max posts to scan per poll
    include_op_context  : Mapped[bool] = mapped_column(Boolean, default=True)
    max_comment_chars   : Mapped[int]  = mapped_column(Integer, default=500)

    # Auto-Pilot guardrails
    is_auto_pilot_enabled           : Mapped[bool]  = mapped_column(Boolean, default=False)
    auto_pilot_confidence_threshold : Mapped[float] = mapped_column(Float, default=0.95)
    auto_pilot_daily_limit          : Mapped[int]   = mapped_column(Integer, default=3)
    # Live counter in Redis: autopilot:count:{id}:{YYYY-MM-DD} EXPIREAT midnight UTC
    last_auto_post_at : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    organization : Mapped["Organization"]    = relationship(back_populates="campaigns")
    drafts       : Mapped[List["DraftReply"]]= relationship(back_populates="campaign")

    __table_args__ = (
        Index("idx_campaign_keywords_gin", "keywords", postgresql_using="gin"),
        # Partial index: only active campaigns (Teammate 2)
        Index("idx_campaign_active", "org_id",
              postgresql_where="status = 'ACTIVE'"),
    )


# ── DraftReply — Complete V6 ──────────────────────────────────────────────────

class DraftReply(Base):
    """
    Central workflow record. Includes full provenance fields for debugging,
    TryEval export, cost tracking, and compliance.
    """
    __tablename__ = "draft_replies"

    id          : Mapped[int] = mapped_column(primary_key=True)
    campaign_id : Mapped[int] = mapped_column(ForeignKey("campaigns.id"))

    # Timestamps
    created_at   : Mapped[datetime]            = mapped_column(default=now_utc, index=True)
    updated_at   : Mapped[datetime]            = mapped_column(default=now_utc, onupdate=now_utc)
    published_at : Mapped[Optional[datetime]]  = mapped_column(DateTime(timezone=True))

    # Reddit Context
    reddit_post_id  : Mapped[str] = mapped_column(String(50), index=True)
    reddit_post_url : Mapped[str] = mapped_column(String(500), nullable=False)
    original_text   : Mapped[str] = mapped_column(Text)

    # AI Output & Provenance
    ai_draft_text             : Mapped[str]            = mapped_column(Text)
    confidence_score          : Mapped[float]          = mapped_column(Float)
    model_used                : Mapped[Optional[str]]  = mapped_column(String(100))     # 'gemini-1.5-flash'
    prompt_template_version   : Mapped[Optional[str]]  = mapped_column(String(100))     # NEW V6: e.g. 'triage_v2'
    model_payload_token_count : Mapped[Optional[int]]  = mapped_column(Integer)         # Tokens sent to LLM
    response_token_count      : Mapped[Optional[int]]  = mapped_column(Integer)         # Tokens returned
    truncation_applied        : Mapped[bool]           = mapped_column(Boolean, default=False)
    truncation_details        : Mapped[Optional[dict]] = mapped_column(JSONB)            # {removed_count, summarized_count}
    prompt_payload            : Mapped[Optional[dict]] = mapped_column(JSONB)            # Full compiled prompt + metadata

    # Failure tracking
    failed_reason : Mapped[Optional[str]] = mapped_column(String(1000))

    # Workflow State
    status            : Mapped[DraftStatus]        = mapped_column(default=DraftStatus.PENDING, index=True)
    locked_by_user_id : Mapped[Optional[int]]      = mapped_column(ForeignKey("users.id"))
    locked_at         : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Publishing Execution
    approved_by_user_id    : Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    published_by_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reddit_accounts.id"))
    live_reddit_url        : Mapped[Optional[str]] = mapped_column(String(500))
    is_auto_pilot_published: Mapped[bool]          = mapped_column(Boolean, default=False)

    # Prompt template reference
    prompt_template_id : Mapped[Optional[int]] = mapped_column(ForeignKey("prompt_templates.id"))

    campaign: Mapped["Campaign"] = relationship(back_populates="drafts")

    __table_args__ = (
        # Idempotency: one reply per campaign per Reddit post
        UniqueConstraint("campaign_id", "reddit_post_id", name="uq_draft_campaign_post"),
        # Primary inbox query: campaign + status + time
        Index("idx_draft_campaign_status_created", "campaign_id", "status", "created_at"),
        # Cross-org status queries (Teammate 2)
        Index("idx_draft_status_org", "campaign_id", "status"),
        # Full-text search on draft content (NEW V6 — Teammate 2)
        Index("idx_draftreply_ai_text_fts", "ai_draft_text",
              postgresql_using="gin",
              postgresql_ops={"ai_draft_text": "gin_trgm_ops"}),
        # Full-text search on original Reddit thread text (NEW V6)
        Index("idx_draftreply_original_text_fts", "original_text",
              postgresql_using="gin",
              postgresql_ops={"original_text": "gin_trgm_ops"}),
    )


# ── PromptTemplate ────────────────────────────────────────────────────────────

class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id                : Mapped[int]           = mapped_column(primary_key=True)
    title             : Mapped[str]           = mapped_column(String(255), nullable=False)
    description       : Mapped[str]           = mapped_column(Text)
    category          : Mapped[str]           = mapped_column(String(100))       # 'Master Context','Tone','Keywords'
    prompt_body       : Mapped[str]           = mapped_column(Text, nullable=False)
    version           : Mapped[int]           = mapped_column(Integer, default=1) # Increment on system updates
    is_system_default : Mapped[bool]          = mapped_column(Boolean, default=True)
    org_id            : Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"))
    # org_id=NULL → system default; org_id set → org custom template

    __table_args__ = (
        UniqueConstraint("org_id", "title", name="uq_org_prompt_title"),
    )


# ── AuditLog ──────────────────────────────────────────────────────────────────

class AuditLog(Base):
    """
    Immutable. Never updated after insert.
    Anonymized (org_id→NULL, details PII stripped) on org erasure — not deleted.

    action examples:
        DRAFT_PUBLISHED, AUTO_PUBLISHED, KILLSWITCH_ACTIVATED, KILLSWITCH_POST_DELETED,
        LOCK_FORCE_TAKEN, API_RATE_LIMIT_HIT, ENCRYPTION_KEY_ROTATED, SUPER_ADMIN_PROMOTED,
        CAMPAIGN_ARCHIVED, SAFETY_PROFILE_CREATED, PERSONA_TOKENS_RECALCULATED,
        COST_LIMIT_EXCEEDED, ORG_DATA_EXPORT_REQUESTED, ORG_DATA_DELETED
    """
    __tablename__ = "audit_logs"

    id      : Mapped[int]           = mapped_column(primary_key=True)
    org_id  : Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id : Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))     # NULL = Auto-Pilot

    action    : Mapped[str]      = mapped_column(String(100))
    details   : Mapped[dict]     = mapped_column(JSONB)
    timestamp : Mapped[datetime] = mapped_column(default=now_utc, index=True)

    organization: Mapped[Optional["Organization"]] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_org_time", "org_id", "timestamp"),
        Index("idx_audit_details_gin", "details", postgresql_using="gin"),
    )
