import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from backend.database import get_db
from backend.models import Organization, OrgPersona, DraftReply, Campaign
# Use the same auth mock/dependency as org.py for consistency
from backend.api.org import get_current_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["Export"])

@router.get("/tryeval")
async def export_tryeval(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Generate a JSON payload for TryEval benchmarking.
    TRD Section 5.8 implementation.
    """
    org_id = session.get("org_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Organization context missing")

    # 1. Fetch Organization and Persona
    org_stmt = select(Organization).options(joinedload(Organization.persona)).where(Organization.id == org_id)
    org_result = await db.execute(org_stmt)
    org = org_result.scalar_one_or_none()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # 2. Fetch Drafts linked to this Org's campaigns
    # Filter DraftReply via Campaign.org_id
    drafts_stmt = (
        select(DraftReply)
        .join(Campaign)
        .where(Campaign.org_id == org_id)
    )
    drafts_result = await db.execute(drafts_stmt)
    drafts = drafts_result.scalars().all()

    # 3. Format Persona Data
    persona_data = {}
    if org.persona:
        persona_data = {
            "master_context": org.persona.master_context,
            "rulesets": org.persona.rulesets_dos_donts,
            "tone_guidelines": org.persona.tone_guidelines,
            "persona_updated_at": org.persona.created_at.isoformat() if org.persona.created_at else None # Using created_at since updated_at isn't explicitly in models.py base
        }

    # 4. Map Drafts to Contract
    export_drafts = []
    for d in drafts:
        export_drafts.append({
            "draft_id": d.id,
            "reddit_post_url": d.reddit_post_url,
            "original_thread": d.original_text,
            "generated_reply": d.ai_draft_text,
            "model_used": d.model_used,
            "prompt_template_version": d.prompt_template_version, # Critical V6 Addition
            "model_payload_tokens": d.model_payload_token_count,
            "confidence_score": d.confidence_score,
            "truncation_applied": d.truncation_applied,
            "status": d.status,
            "live_reddit_url": d.live_reddit_url,
            "is_auto_pilot": d.is_auto_pilot_published
        })

    # 5. Build Final Payload (Teammate 2 defaults)
    payload = {
        "export_version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "org_name": org.name,
        "persona": persona_data,
        "drafts": export_drafts,
        "benchmark_against": ["gpt-4o", "claude-3-5-sonnet-20241022"]
    }

    return payload
