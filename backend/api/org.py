from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import litellm
import os

from backend.database import get_db
from backend.models import OrgLLMConfig, OrgPersona, Organization
from backend.schemas import LLMConfigUpdate, PersonaUpdate
from backend.utils.tokenizer import (
    count_tokens, 
    update_persona_token_counts, 
    DEFAULT_MODEL
)
from backend.utils.encryption import encrypt
from backend.utils.audit import write_audit_log
from backend.limiter import limiter

router = APIRouter(prefix="/api/org", tags=["organization"])

# Mocking auth for now as per instructions (focus is on logic/rate limiting)
# Teammate 2: In production, this session dictionary is populated by Clerk JWT validation.
async def get_current_session():
    """Fallback mock session for development."""
    return {"org_id": 1, "user_id": 1}

@router.patch("/llm-config")
@limiter.limit("5/minute")
async def update_llm_config(
    payload: LLMConfigUpdate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Update the organization's LLM configuration.
    If model_name changes, triggers token count recalculation on the persona.
    """
    org_id = session["org_id"]
    
    # 1. Fetch existing config
    stmt = select(OrgLLMConfig).where(OrgLLMConfig.org_id == org_id)
    result = await db.execute(stmt)
    old_config = result.scalar_one_or_none()
    
    model_changed = old_config and old_config.model_name != payload.model_name

    # 2. Update or create config
    config_data = payload.dict(exclude={"api_key"})
    if payload.api_key:
        config_data["encrypted_api_key"] = encrypt(payload.api_key)
        # Ensure key version is tracked (Teammate 3)
        config_data["encrypted_with_key_version"] = 1
    
    if old_config:
        for key, value in config_data.items():
            setattr(old_config, key, value)
    else:
        new_config = OrgLLMConfig(**config_data, org_id=org_id)
        db.add(new_config)
    
    await db.flush()

    # 3. Handle model change (Teammate 1: Chicken & Egg Problem)
    if model_changed:
        stmt = select(OrgPersona).where(OrgPersona.org_id == org_id)
        result = await db.execute(stmt)
        persona = result.scalar_one_or_none()
        
        if persona:
            update_persona_token_counts(persona, payload.model_name)
            await write_audit_log(
                db, 
                org_id, 
                action='PERSONA_TOKENS_RECALCULATED',
                details={'new_model': payload.model_name},
                user_id=session["user_id"]
            )
    
    await db.commit()
    return {"status": "success", "model_changed": model_changed}

@router.patch("/persona")
@limiter.limit("5/minute")
async def update_persona(
    payload: PersonaUpdate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Update organization persona and validate token budget.
    Rejects save if persona consumes > 80% of model context window (Teammate 4).
    """
    org_id = session["org_id"]
    
    # 1. Determine model for token calculation
    stmt = select(OrgLLMConfig).where(OrgLLMConfig.org_id == org_id)
    result = await db.execute(stmt)
    llm_config = result.scalar_one_or_none()
    
    model = llm_config.model_name if llm_config else DEFAULT_MODEL
    
    try:
        model_limit = litellm.get_max_tokens(model)
        if not isinstance(model_limit, int):
            model_limit = 4096
    except:
        model_limit = 4096

    # 2. Compute current token overhead
    ctx_tokens     = count_tokens(model, payload.master_context or '')
    ruleset_tokens = count_tokens(model, str(payload.rulesets_dos_donts or ''))
    total          = ctx_tokens + ruleset_tokens

    # 3. Guardrail check
    if total > model_limit * 0.80:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f'Your Master Context + Rulesets use {total:,} tokens, which exceeds '
                f'80% of {model}\'s {model_limit:,}-token limit. '
                f'Reduce your content to leave room for Reddit thread context.'
            )
        )

    # 4. Save persona and pre-computed counts
    stmt = select(OrgPersona).where(OrgPersona.org_id == org_id)
    result = await db.execute(stmt)
    persona = result.scalar_one_or_none()
    
    persona_data = payload.dict()
    if persona:
        for key, value in persona_data.items():
            setattr(persona, key, value)
    else:
        persona = OrgPersona(**persona_data, org_id=org_id)
        db.add(persona)
    
    persona.master_context_tokens = ctx_tokens
    persona.rulesets_token_count = ruleset_tokens
    
    await db.commit()
    return {"status": "success", "tokens_used": total}
