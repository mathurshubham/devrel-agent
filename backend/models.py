import enum
from datetime import datetime, date, timezone
from typing import List, Optional
from sqlalchemy import (
    String, Boolean, Integer, ForeignKey, DateTime, Date,
    Text, UniqueConstraint, Index, Numeric,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def now_utc():
    return datetime.now(timezone.utc)


# ── Enums ─────────────────────────────────────────────────────────────────────

class PlatformEnum(str, enum.Enum):
    REDDIT   = "REDDIT"
    LINKEDIN = "LINKEDIN"
    TWITTER  = "TWITTER"


class DraftStatus(str, enum.Enum):
    PENDING            = "PENDING"
    AWAITING_CONFIRM   = "AWAITING_CONFIRM"
    POSTED             = "POSTED"
    REJECTED           = "REJECTED"
    IGNORED            = "IGNORED"
    FAILED             = "FAILED"
    FAILED_COST_LIMIT  = "FAILED_COST_LIMIT"


class ReplyType(str, enum.Enum):
    NEW_COMMENT       = "NEW_COMMENT"
    REPLY_TO_COMMENT  = "REPLY_TO_COMMENT"


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN       = "ADMIN"
    MEMBER      = "MEMBER"


class PromptType(str, enum.Enum):
    MASTER_CONTEXT = "MASTER_CONTEXT"
    ANGLE          = "ANGLE"
    SCOUT          = "SCOUT"
    ANALYST        = "ANALYST"


class CampaignStatus(str, enum.Enum):
    ACTIVE   = "ACTIVE"
    PAUSED   = "PAUSED"
    ARCHIVED = "ARCHIVED"


# ── Organization ──────────────────────────────────────────────────────────────

class Organization(Base):
    __tablename__ = "organizations"

    id           : Mapped[int]      = mapped_column(primary_key=True)
    clerk_org_id : Mapped[str]      = mapped_column(String(255), unique=True, index=True)
    name         : Mapped[str]      = mapped_column(String(255), nullable=False)
    is_active    : Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at   : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    memberships     : Mapped[List["OrgMembership"]]         = relationship(back_populates="organization")
    campaigns       : Mapped[List["Campaign"]]               = relationship(back_populates="organization")
    llm_config      : Mapped[Optional["OrgLLMConfig"]]       = relationship(back_populates="organization")
    persona         : Mapped[Optional["OrgPersona"]]         = relationship(back_populates="organization")
    settings        : Mapped[Optional["OrgSettings"]]        = relationship(back_populates="organization")
    audit_logs      : Mapped[List["AuditLog"]]               = relationship(back_populates="organization")


# ── User — Clerk-synced ───────────────────────────────────────────────────────

class User(Base):
    """No hashed_password — auth is fully managed by Clerk."""
    __tablename__ = "users"

    id             : Mapped[int]      = mapped_column(primary_key=True)
    clerk_user_id  : Mapped[str]      = mapped_column(String(255), unique=True, index=True)
    email          : Mapped[str]      = mapped_column(String(255), index=True)
    role           : Mapped[UserRole] = mapped_column(default=UserRole.MEMBER)
    created_at     : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    memberships: Mapped[List["OrgMembership"]] = relationship(back_populates="user")


# ── OrgMembership ─────────────────────────────────────────────────────────────

class OrgMembership(Base):
    """Many-to-many join between Organization and User, with a per-org role."""
    __tablename__ = "org_memberships"

    id      : Mapped[int] = mapped_column(primary_key=True)
    org_id  : Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_id : Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role    : Mapped[str] = mapped_column(String(50), default=UserRole.MEMBER.value)

    organization: Mapped["Organization"] = relationship(back_populates="memberships")
    user        : Mapped["User"]         = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_membership_org_user"),
    )


# ── OrgLLMConfig — BYOK LLM Vault ─────────────────────────────────────────────

class OrgLLMConfig(Base):
    """BYOK vault for LLM credentials. One record per org. OpenRouter is default."""
    __tablename__ = "org_llm_configs"

    id     : Mapped[int] = mapped_column(primary_key=True)
    org_id : Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True)

    provider                   : Mapped[str]           = mapped_column(String(50), default="openrouter")
    model_name                 : Mapped[Optional[str]] = mapped_column(String(150))
    custom_base_url            : Mapped[Optional[str]] = mapped_column(String(500))
    encrypted_api_key          : Mapped[Optional[str]] = mapped_column(Text)
    encrypted_with_key_version : Mapped[int]           = mapped_column(Integer, default=1)

    max_daily_llm_tokens      : Mapped[Optional[int]]   = mapped_column(Integer)
    max_monthly_llm_cost_usd  : Mapped[Optional[float]] = mapped_column(Numeric(10, 4))

    organization: Mapped["Organization"] = relationship(back_populates="llm_config")


# ── OrgPersona — Context Engine ───────────────────────────────────────────────

class OrgPersona(Base):
    __tablename__ = "org_personas"

    id     : Mapped[int] = mapped_column(primary_key=True)
    org_id : Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True)

    master_context             : Mapped[Optional[str]]  = mapped_column(Text)
    rulesets_dos_donts         : Mapped[Optional[dict]] = mapped_column(JSONB)
    tone_guidelines            : Mapped[Optional[str]]  = mapped_column(Text)
    master_context_token_count : Mapped[int]            = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    organization: Mapped["Organization"] = relationship(back_populates="persona")

    __table_args__ = (
        Index("idx_orgpersona_rulesets_gin", "rulesets_dos_donts", postgresql_using="gin"),
    )


# ── OrgSettings ────────────────────────────────────────────────────────────────

class OrgSettings(Base):
    __tablename__ = "org_settings"

    id     : Mapped[int] = mapped_column(primary_key=True)
    org_id : Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True)

    reply_hook                    : Mapped[Optional[str]]   = mapped_column(Text)
    scout_prompt                  : Mapped[Optional[str]]   = mapped_column(Text)
    apify_monthly_budget_usd      : Mapped[float]           = mapped_column(Numeric(10, 2), default=50)
    actor_overrides               : Mapped[dict]            = mapped_column(JSONB, default=dict)
    linkedin_stale_days           : Mapped[Optional[int]]   = mapped_column(Integer)
    linkedin_stale_min_engagement : Mapped[Optional[int]]   = mapped_column(Integer)
    analyst_enabled               : Mapped[bool]            = mapped_column(Boolean, default=False)
    disclosure_reddit             : Mapped[bool]            = mapped_column(Boolean, default=True)
    pillar_taxonomy               : Mapped[Optional[dict]]  = mapped_column(JSONB)

    organization: Mapped["Organization"] = relationship(back_populates="settings")


# ── OrgApifyToken ──────────────────────────────────────────────────────────────

class OrgApifyToken(Base):
    __tablename__ = "org_apify_tokens"

    id     : Mapped[int] = mapped_column(primary_key=True)
    org_id : Mapped[int] = mapped_column(ForeignKey("organizations.id"))

    label                      : Mapped[str]           = mapped_column(String(100))
    encrypted_token            : Mapped[str]            = mapped_column(Text, nullable=False)
    encrypted_with_key_version : Mapped[int]            = mapped_column(Integer, default=1)
    plan_cap_usd               : Mapped[float]           = mapped_column(Numeric(10, 2), default=5.00)
    is_active                  : Mapped[bool]            = mapped_column(Boolean, default=True)
    created_at                 : Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=now_utc)


# ── Campaign ──────────────────────────────────────────────────────────────────

class Campaign(Base):
    __tablename__ = "campaigns"

    id     : Mapped[int] = mapped_column(primary_key=True)
    org_id : Mapped[int] = mapped_column(ForeignKey("organizations.id"))

    platform : Mapped[PlatformEnum] = mapped_column(index=True)
    name     : Mapped[str]          = mapped_column(String(255), nullable=False)
    value    : Mapped[Optional[str]] = mapped_column(Text)

    status                  : Mapped[CampaignStatus] = mapped_column(default=CampaignStatus.ACTIVE, index=True)
    poll_frequency_minutes  : Mapped[int]             = mapped_column(Integer, default=240)
    keywords                : Mapped[list]            = mapped_column(JSONB, default=list)
    platform_config         : Mapped[dict]            = mapped_column(JSONB, default=dict)
    daily_draft_cap         : Mapped[int]             = mapped_column(Integer, default=3)

    created_at : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    organization : Mapped["Organization"]     = relationship(back_populates="campaigns")
    drafts       : Mapped[List["DraftReply"]] = relationship(back_populates="campaign")

    __table_args__ = (
        Index("idx_campaign_keywords_gin", "keywords", postgresql_using="gin"),
        Index("idx_campaign_active", "org_id", postgresql_where="status = 'ACTIVE'"),
    )


# ── DraftReply — Complete V7 ───────────────────────────────────────────────────

class DraftReply(Base):
    """Central workflow record for the HITL review pipeline."""
    __tablename__ = "draft_replies"

    id          : Mapped[int] = mapped_column(primary_key=True)
    org_id      : Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    campaign_id : Mapped[int] = mapped_column(ForeignKey("campaigns.id"))

    platform : Mapped[PlatformEnum] = mapped_column(index=True)
    post_id  : Mapped[str]          = mapped_column(String(100), index=True)

    author              : Mapped[Optional[str]] = mapped_column(String(255))
    author_name         : Mapped[Optional[str]] = mapped_column(String(255))
    author_headline     : Mapped[Optional[str]] = mapped_column(String(500))
    author_profile_url  : Mapped[Optional[str]] = mapped_column(String(500))

    title            : Mapped[Optional[str]] = mapped_column(Text)
    original_content : Mapped[Optional[str]] = mapped_column(Text)
    top_comments     : Mapped[Optional[list]] = mapped_column(JSONB)
    url              : Mapped[Optional[str]] = mapped_column(String(500))
    reply_target_url : Mapped[Optional[str]] = mapped_column(String(500))

    reply_type              : Mapped[ReplyType]         = mapped_column(default=ReplyType.NEW_COMMENT)
    target_comment_id       : Mapped[Optional[str]]     = mapped_column(String(100))
    target_comment_content  : Mapped[Optional[str]]     = mapped_column(Text)

    angle_name    : Mapped[Optional[str]] = mapped_column(String(255))
    ai_draft_text : Mapped[Optional[str]] = mapped_column(Text)

    status            : Mapped[DraftStatus]        = mapped_column(default=DraftStatus.PENDING, index=True)
    confidence        : Mapped[Optional[float]]    = mapped_column()
    triage_reasoning  : Mapped[Optional[str]]       = mapped_column(Text)
    signal_tier       : Mapped[Optional[str]]       = mapped_column(String(50))

    reactions         : Mapped[int] = mapped_column(Integer, default=0)
    comments_count    : Mapped[int] = mapped_column(Integer, default=0)
    shares            : Mapped[int] = mapped_column(Integer, default=0)
    engagement_score  : Mapped[int] = mapped_column(Integer, default=0)

    posted_at_source : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    live_url         : Mapped[Optional[str]]      = mapped_column(String(500))
    reject_reason    : Mapped[Optional[str]]      = mapped_column(String(1000))

    model_used              : Mapped[Optional[str]]  = mapped_column(String(100))
    prompt_template_version : Mapped[Optional[str]]  = mapped_column(String(100))
    prompt_payload           : Mapped[Optional[dict]] = mapped_column(JSONB)
    response_token_count     : Mapped[Optional[int]]  = mapped_column(Integer)

    locked_by_user_id : Mapped[Optional[int]]      = mapped_column(ForeignKey("users.id"))
    locked_at         : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)
    updated_at : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    campaign: Mapped["Campaign"] = relationship(back_populates="drafts")

    __table_args__ = (
        UniqueConstraint("campaign_id", "post_id", name="uq_draft_campaign_post"),
        Index("idx_draft_campaign_status_created", "campaign_id", "status", "created_at"),
        Index("idx_draft_status_org", "org_id", "status"),
        Index(
            "idx_draftreply_original_content_fts", "original_content",
            postgresql_using="gin", postgresql_ops={"original_content": "gin_trgm_ops"},
        ),
        Index(
            "idx_draftreply_ai_draft_text_fts", "ai_draft_text",
            postgresql_using="gin", postgresql_ops={"ai_draft_text": "gin_trgm_ops"},
        ),
    )


# ── PostedHistory ──────────────────────────────────────────────────────────────

class PostedHistory(Base):
    __tablename__ = "posted_history"

    id       : Mapped[int]          = mapped_column(primary_key=True)
    org_id   : Mapped[int]          = mapped_column(ForeignKey("organizations.id"))
    platform : Mapped[PlatformEnum] = mapped_column()
    post_id  : Mapped[str]          = mapped_column(String(100))
    posted_at: Mapped[datetime]     = mapped_column(DateTime(timezone=True), default=now_utc)

    __table_args__ = (
        UniqueConstraint("org_id", "platform", "post_id", name="uq_posted_history_org_platform_post"),
    )


# ── EngagementOutcome ──────────────────────────────────────────────────────────

class EngagementOutcome(Base):
    __tablename__ = "engagement_outcomes"

    id             : Mapped[int]           = mapped_column(primary_key=True)
    draft_id       : Mapped[int]           = mapped_column(ForeignKey("draft_replies.id"))
    hours_after    : Mapped[int]           = mapped_column(Integer)
    reactions      : Mapped[int]           = mapped_column(Integer, default=0)
    replies        : Mapped[int]           = mapped_column(Integer, default=0)
    reposts        : Mapped[int]           = mapped_column(Integer, default=0)
    got_response   : Mapped[bool]          = mapped_column(Boolean, default=False)
    checked_at     : Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=now_utc)


# ── PromptTemplate ────────────────────────────────────────────────────────────

class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id       : Mapped[int]                = mapped_column(primary_key=True)
    org_id   : Mapped[Optional[int]]      = mapped_column(ForeignKey("organizations.id"), nullable=True)
    platform : Mapped[Optional[PlatformEnum]] = mapped_column(nullable=True)
    type     : Mapped[PromptType]         = mapped_column()
    name     : Mapped[str]                = mapped_column(String(255), nullable=False)
    content  : Mapped[str]                = mapped_column(Text, nullable=False)
    version  : Mapped[int]                = mapped_column(Integer, default=1)

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_org_prompt_name"),
    )


# ── SubredditSafetyProfile ────────────────────────────────────────────────────

class SubredditSafetyProfile(Base):
    """Per-org safety overrides for Reddit subreddits (or equivalent per-community caps)."""
    __tablename__ = "subreddit_safety_profiles"

    id                     : Mapped[int]          = mapped_column(primary_key=True)
    org_id                 : Mapped[int]          = mapped_column(ForeignKey("organizations.id"))
    subreddit              : Mapped[str]          = mapped_column(String(100), nullable=False)

    max_daily_drafts       : Mapped[int]           = mapped_column(Integer, default=3)
    require_manual_review  : Mapped[bool]          = mapped_column(Boolean, default=True)
    notes                  : Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("org_id", "subreddit", name="uq_org_subreddit_safety"),
    )


# ── AuditLog ──────────────────────────────────────────────────────────────────

class AuditLog(Base):
    """Immutable. Never updated after insert."""
    __tablename__ = "audit_logs"

    id      : Mapped[int]           = mapped_column(primary_key=True)
    org_id  : Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id : Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    action    : Mapped[str]      = mapped_column(String(100))
    details   : Mapped[dict]     = mapped_column(JSONB)
    timestamp : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)

    organization: Mapped[Optional["Organization"]] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_org_time", "org_id", "timestamp"),
        Index("idx_audit_details_gin", "details", postgresql_using="gin"),
    )


# ── ProcessedWebhookEvent ─────────────────────────────────────────────────────

class ProcessedWebhookEvent(Base):
    """Clerk/Svix webhook idempotency table, keyed by svix-id."""
    __tablename__ = "processed_webhook_events"

    svix_id      : Mapped[str]      = mapped_column(String(255), primary_key=True)
    processed_at : Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


# ── SystemLog ──────────────────────────────────────────────────────────────────

class SystemLog(Base):
    __tablename__ = "system_logs"

    id         : Mapped[int]           = mapped_column(primary_key=True)
    org_id     : Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    level      : Mapped[str]           = mapped_column(String(20))
    module     : Mapped[str]           = mapped_column(String(100))
    message    : Mapped[str]           = mapped_column(Text)
    created_at : Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=now_utc)


# ── Analyst set ───────────────────────────────────────────────────────────────

class AnalystRun(Base):
    __tablename__ = "analyst_runs"

    id          : Mapped[int]                = mapped_column(primary_key=True)
    org_id      : Mapped[int]                = mapped_column(ForeignKey("organizations.id"))
    week_of     : Mapped[date]               = mapped_column(Date)
    status      : Mapped[str]                = mapped_column(String(50), default="PENDING")
    started_at  : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PostClassification(Base):
    __tablename__ = "post_classifications"

    id             : Mapped[int]           = mapped_column(primary_key=True)
    run_id         : Mapped[int]           = mapped_column(ForeignKey("analyst_runs.id"))
    source_meta    : Mapped[dict]          = mapped_column(JSONB, default=dict)
    decision       : Mapped[Optional[str]] = mapped_column(String(50))
    relevance      : Mapped[Optional[int]] = mapped_column(Integer)
    signal         : Mapped[Optional[int]] = mapped_column(Integer)
    buyer_persona  : Mapped[Optional[str]] = mapped_column(String(255))
    watch_tier     : Mapped[Optional[str]] = mapped_column(String(50))


class TopicCluster(Base):
    __tablename__ = "topic_clusters"

    id     : Mapped[int]      = mapped_column(primary_key=True)
    run_id : Mapped[int]      = mapped_column(ForeignKey("analyst_runs.id"))
    pillar : Mapped[str]      = mapped_column(String(255))
    count  : Mapped[int]      = mapped_column(Integer, default=0)
    posts  : Mapped[list]     = mapped_column(JSONB, default=list)


class StanceObservation(Base):
    __tablename__ = "stance_observations"

    id             : Mapped[int]           = mapped_column(primary_key=True)
    run_id         : Mapped[int]           = mapped_column(ForeignKey("analyst_runs.id"))
    post_ref       : Mapped[str]           = mapped_column(String(500))
    stance         : Mapped[Optional[str]] = mapped_column(String(50))
    confidence     : Mapped[Optional[float]] = mapped_column()
    evidence_quote : Mapped[Optional[str]] = mapped_column(Text)


class QuoteWorthyClaim(Base):
    __tablename__ = "quote_worthy_claims"

    id       : Mapped[int]           = mapped_column(primary_key=True)
    run_id   : Mapped[int]           = mapped_column(ForeignKey("analyst_runs.id"))
    post_ref : Mapped[str]           = mapped_column(String(500))
    quote    : Mapped[str]           = mapped_column(Text)
    author   : Mapped[Optional[str]] = mapped_column(String(255))


class IntelBrief(Base):
    __tablename__ = "intel_briefs"

    id         : Mapped[int]  = mapped_column(primary_key=True)
    org_id     : Mapped[int]  = mapped_column(ForeignKey("organizations.id"))
    week_of    : Mapped[date] = mapped_column(Date)
    content_md : Mapped[str]  = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("org_id", "week_of", name="uq_intel_brief_org_week"),
    )


class TargetAuthor(Base):
    __tablename__ = "target_authors"

    id          : Mapped[int]           = mapped_column(primary_key=True)
    org_id      : Mapped[int]           = mapped_column(ForeignKey("organizations.id"))
    name        : Mapped[str]           = mapped_column(String(255))
    tier        : Mapped[Optional[int]] = mapped_column(Integer)
    profile_url : Mapped[Optional[str]] = mapped_column(String(500))


class Competitor(Base):
    __tablename__ = "competitors"

    id       : Mapped[int]                = mapped_column(primary_key=True)
    org_id   : Mapped[int]                = mapped_column(ForeignKey("organizations.id"))
    platform : Mapped[Optional[PlatformEnum]] = mapped_column(nullable=True)
    name     : Mapped[str]                = mapped_column(String(255))
    url      : Mapped[Optional[str]]      = mapped_column(String(500))
