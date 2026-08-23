from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, update
import litellm
import os
from datetime import date
from typing import List
import redis.asyncio as redis

from backend.database import get_db
from backend.models import OrgLLMConfig, OrgPersona, OrgSettings, AuditLog, Campaign, CampaignStatus, User, UserRole
from backend.schemas import (
    LLMConfigUpdate, PersonaUpdate, PersonaResponse, AuditLogSchema, OrgUsageSchema,
    OrgSettingsResponse, OrgSettingsUpdate,
    ALLOWED_LLM_PROVIDERS,
)
from backend.utils.tokenizer import (
    count_tokens,
    update_persona_token_counts,
    DEFAULT_MODEL,
)
from backend.utils.encryption import encrypt
from backend.utils.audit import write_audit_log
from backend.limiter import limiter
from backend.utils.auth import get_current_session
from backend.tasks.scheduler import remove_campaign

router = APIRouter(prefix="/api/org", tags=["Organization"])

# FastAPI (uvicorn) runs a single long-lived event loop for the process, so
# a module-level redis client here is safe -- unlike the Celery task bodies
# fixed in backend/utils/celery_async.py, which each get their own
# asyncio.run() event loop and need a fresh client per invocation instead.
_REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
_redis_client = redis.from_url(_REDIS_URL)


async def _require_org_admin(db: AsyncSession, session: dict) -> None:
    """Org settings now control real spend (``apify_monthly_budget_usd``)
    and feature opt-ins with cost implications (``analyst_enabled``) --
    writing them requires the org ADMIN role (or the platform SUPER_ADMIN
    role on the caller's own User row), not any MEMBER."""
    if session.get("role") == UserRole.ADMIN.value:
        return
    user = await db.get(User, session["user_id"])
    if user and user.role == UserRole.SUPER_ADMIN:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")


@router.get("/usage", response_model=OrgUsageSchema)
async def get_org_usage(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Fetch daily token and monthly cost usage from Redis."""
    org_id = session["org_id"]

    daily_key = f"llm:tokens:{org_id}:{date.today().isoformat()}"
    month_key = f"llm:cost_usd:{org_id}:{date.today().strftime('%Y-%m')}"

    daily_tokens = await _redis_client.get(daily_key)
    monthly_cost = await _redis_client.get(month_key)

    stmt = select(OrgLLMConfig).where(OrgLLMConfig.org_id == org_id)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    return {
        "daily_tokens": int(daily_tokens or 0),
        "monthly_cost_usd": float(monthly_cost or 0.0),
        "max_daily_tokens": config.max_daily_llm_tokens if config else None,
        "max_monthly_cost": config.max_monthly_llm_cost_usd if config else None
    }


@router.get("/audit-logs", response_model=List[AuditLogSchema])
async def get_audit_logs(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Fetch the organization's audit log history."""
    org_id = session["org_id"]
    stmt = select(AuditLog).where(AuditLog.org_id == org_id).order_by(desc(AuditLog.timestamp)).limit(100)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/kill-switch")
async def activate_kill_switch(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Emergency stop: pauses all active campaigns and removes them from the scheduler ZSET."""
    org_id = session["org_id"]

    # 1. Find active campaigns so we can also pull them out of the scheduler.
    result = await db.execute(
        select(Campaign.id).where(Campaign.org_id == org_id, Campaign.status == CampaignStatus.ACTIVE)
    )
    active_campaign_ids = [row[0] for row in result.all()]

    # 2. Pause all active campaigns.
    await db.execute(
        update(Campaign)
        .where(Campaign.org_id == org_id, Campaign.status == CampaignStatus.ACTIVE)
        .values(status=CampaignStatus.PAUSED)
    )

    # 3. Remove them from the Redis scheduler ZSET so they stop being polled.
    for campaign_id in active_campaign_ids:
        await remove_campaign(campaign_id)

    # 4. Audit log — must be flushed before the final commit or it's lost.
    await write_audit_log(
        db,
        org_id,
        action='KILLSWITCH_ACTIVATED',
        details={'reason': 'Manual emergency stop triggered via Settings', 'campaign_ids': active_campaign_ids},
        user_id=session["user_id"]
    )

    await db.commit()
    return {"status": "success", "message": "All campaigns have been paused."}


@router.get("/status")
async def get_org_status(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Returns LLM provider connectivity status. Used by the Vaults dashboard."""
    org_id = session["org_id"]

    stmt = select(OrgLLMConfig).where(OrgLLMConfig.org_id == org_id)
    result = await db.execute(stmt)
    llm_config = result.scalar_one_or_none()

    return {
        "openai_connected": llm_config.provider == "openai" if llm_config else False,
        "anthropic_connected": llm_config.provider == "anthropic" if llm_config else False,
        "gemini_connected": llm_config.provider == "gemini" if llm_config else False,
        "openrouter_connected": llm_config.provider == "openrouter" if llm_config else False,
        "ollama_connected": llm_config.provider == "ollama" if llm_config else False,
        "custom_connected": llm_config.provider == "custom" if llm_config else False,
        "current_model": llm_config.model_name if llm_config else None,
        "current_provider": llm_config.provider if llm_config else None,
    }


@router.patch("/llm-config")
@limiter.limit("5/minute")
async def update_llm_config(
    payload: LLMConfigUpdate,
    request: Request,  # required by slowapi
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Update the organization's LLM configuration. OpenRouter is the default/
    primary provider. If model_name changes, triggers token count
    recalculation on the persona.
    """
    org_id = session["org_id"]

    if payload.provider not in ALLOWED_LLM_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"provider must be one of {sorted(ALLOWED_LLM_PROVIDERS)}",
        )
    if payload.provider in ("custom", "ollama") and not payload.custom_base_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"custom_base_url is required for provider '{payload.provider}'",
        )

    stmt = select(OrgLLMConfig).where(OrgLLMConfig.org_id == org_id)
    result = await db.execute(stmt)
    old_config = result.scalar_one_or_none()

    # Partial-update semantics: an omitted model_name preserves the existing
    # one (or falls back to the platform default on first save).
    effective_model = payload.model_name or (
        old_config.model_name if old_config and old_config.model_name else DEFAULT_MODEL
    )
    model_changed = bool(old_config and old_config.model_name != effective_model)

    config_data = payload.model_dump(exclude={"api_key"})
    config_data["model_name"] = effective_model
    if payload.api_key:
        config_data["encrypted_api_key"] = encrypt(payload.api_key)
        config_data["encrypted_with_key_version"] = 1

    if old_config:
        for key, value in config_data.items():
            setattr(old_config, key, value)
    else:
        new_config = OrgLLMConfig(**config_data, org_id=org_id)
        db.add(new_config)

    await db.flush()

    if model_changed:
        stmt = select(OrgPersona).where(OrgPersona.org_id == org_id)
        result = await db.execute(stmt)
        persona = result.scalar_one_or_none()

        if persona:
            update_persona_token_counts(persona, effective_model)
            await write_audit_log(
                db,
                org_id,
                action='PERSONA_TOKENS_RECALCULATED',
                details={"new_model": effective_model},
                user_id=session["user_id"]
            )

    await db.commit()
    return {"status": "success", "model_changed": model_changed}


@router.get("/persona", response_model=PersonaResponse)
async def get_persona(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Fetch the organization's persona (master context, rulesets, tone
    guidelines). 404s when the org hasn't saved one yet -- the frontend
    treats that as an empty persona to seed the initial-creation form.
    """
    org_id = session["org_id"]

    stmt = select(OrgPersona).where(OrgPersona.org_id == org_id)
    result = await db.execute(stmt)
    persona = result.scalar_one_or_none()

    if not persona:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not configured")

    return persona


@router.patch("/persona")
@limiter.limit("5/minute")
async def update_persona(
    payload: PersonaUpdate,
    request: Request,  # required by slowapi
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Update organization persona and validate token budget.
    Rejects save if persona consumes > 80% of the model's context window.
    """
    org_id = session["org_id"]

    stmt = select(OrgLLMConfig).where(OrgLLMConfig.org_id == org_id)
    result = await db.execute(stmt)
    llm_config = result.scalar_one_or_none()

    model = llm_config.model_name if (llm_config and llm_config.model_name) else DEFAULT_MODEL

    try:
        model_limit = litellm.get_max_tokens(model)
        if not isinstance(model_limit, int):
            model_limit = 4096
    except Exception:
        model_limit = 4096

    combined_text = (payload.master_context or '') + str(payload.rulesets_dos_donts or '')
    total = count_tokens(model, combined_text)

    if total > model_limit * 0.80:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f'Your Master Context + Rulesets use {total:,} tokens, which exceeds '
                f'80% of {model}\'s {model_limit:,}-token limit. '
                f'Reduce your content to leave room for source-platform context.'
            )
        )

    stmt = select(OrgPersona).where(OrgPersona.org_id == org_id)
    result = await db.execute(stmt)
    persona = result.scalar_one_or_none()

    persona_data = payload.model_dump()
    if persona:
        for key, value in persona_data.items():
            setattr(persona, key, value)
    else:
        persona = OrgPersona(**persona_data, org_id=org_id)
        db.add(persona)

    persona.master_context_token_count = total

    await db.commit()
    return {"status": "success", "tokens_used": total}


@router.get("/settings", response_model=OrgSettingsResponse)
async def get_org_settings_endpoint(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Fetch the org's settings (reply hook, scout prompt, LinkedIn staleness
    filter, Analyst opt-in, disclosure default, pillar taxonomy, Apify
    budget). Defaults are returned when the org has no OrgSettings row yet
    -- unlike persona, settings has sensible zero-config defaults so there
    is no "not configured" 404 here.
    """
    org_id = session["org_id"]
    stmt = select(OrgSettings).where(OrgSettings.org_id == org_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()

    if not settings:
        return OrgSettingsResponse()
    return settings


@router.patch("/settings", response_model=OrgSettingsResponse)
@limiter.limit("10/minute")
async def update_org_settings(
    payload: OrgSettingsUpdate,
    request: Request,  # required by slowapi
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Partial update of the org's settings; creates the row on first write."""
    org_id = session["org_id"]
    await _require_org_admin(db, session)

    stmt = select(OrgSettings).where(OrgSettings.org_id == org_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()

    update_data = payload.model_dump(exclude_unset=True)
    if settings:
        for key, value in update_data.items():
            setattr(settings, key, value)
    else:
        settings = OrgSettings(org_id=org_id, **update_data)
        db.add(settings)

    await write_audit_log(
        db, org_id,
        action='ORG_SETTINGS_UPDATED',
        details={'changes': list(update_data.keys())},
        user_id=session["user_id"]
    )

    await db.commit()
    await db.refresh(settings)
    return settings
