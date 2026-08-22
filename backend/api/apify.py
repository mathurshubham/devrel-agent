# MERGE NOTE: this router is not wired up yet. backend/main.py must gain
#   from backend.api.apify import router as apify_router
#   app.include_router(apify_router)
# It was left out of main.py deliberately to avoid conflicting with the
# parallel rewrite of main.py/models.py/routers.

"""Org-facing API for the Apify token vault and cost visibility (PRD V7 §5.2).

Tokens are stored encrypted with the org's current key version and are never
returned to a client — the list endpoint shows a label and the last four
characters only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.ingestion.service import (
    estimate_monthly_cost_usd,
    estimate_run_cost_usd,
    get_month_spend_usd,
    monthly_budget_usd,
    runs_per_month,
)
from backend.ingestion.tokens import (
    ApifyTokenService,
    VaultToken,
    is_valid_apify_token,
    mask_token,
)
from backend.models import Campaign, CampaignStatus, OrgApifyToken, OrgSettings
from backend.utils.auth import get_current_session
from backend.utils.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/org/apify", tags=["Apify"])

CURRENT_KEY_VERSION = 1


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ApifyTokenCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    token: str = Field(min_length=1)


class ApifyTokenUpdate(BaseModel):
    plan_cap_usd: Optional[float] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class ApifyTokenOut(BaseModel):
    id: int
    label: str
    masked_token: str
    plan_cap_usd: float
    is_active: bool
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_tokens(db: AsyncSession, org_id: int, active_only: bool = False):
    stmt = select(OrgApifyToken).where(OrgApifyToken.org_id == org_id)
    if active_only:
        stmt = stmt.where(OrgApifyToken.is_active.is_(True))
    result = await db.execute(stmt.order_by(OrgApifyToken.id))
    return list(result.scalars().all())


async def _load_settings(db: AsyncSession, org_id: int):
    result = await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
    return result.scalar_one_or_none()


async def _get_token_or_404(db: AsyncSession, org_id: int, token_id: int) -> OrgApifyToken:
    result = await db.execute(
        select(OrgApifyToken).where(
            OrgApifyToken.id == token_id, OrgApifyToken.org_id == org_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    return row


def _to_vault_token(row: OrgApifyToken) -> Optional[VaultToken]:
    """Decrypt a stored row into a usable vault token, or None if undecryptable."""
    try:
        plaintext = decrypt(row.encrypted_token, row.encrypted_with_key_version or 1)
    except Exception:
        logger.exception("Could not decrypt Apify token id=%s", row.id)
        return None
    return VaultToken(
        token=plaintext,
        token_id=row.id,
        label=row.label,
        plan_cap_usd=float(row.plan_cap_usd or 5.0),
    )


# ---------------------------------------------------------------------------
# Token CRUD
# ---------------------------------------------------------------------------


@router.post("/tokens", response_model=ApifyTokenOut, status_code=status.HTTP_201_CREATED)
async def create_token(
    payload: ApifyTokenCreate,
    db: AsyncSession = Depends(get_db),
    session=Depends(get_current_session),
):
    """Add an Apify token to the org vault. The secret is encrypted at rest."""
    token = payload.token.strip()
    if not is_valid_apify_token(token):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Apify API tokens start with 'apify_api_'",
        )

    row = OrgApifyToken(
        org_id=session.org_id,
        label=payload.label.strip(),
        encrypted_token=encrypt(token, CURRENT_KEY_VERSION),
        encrypted_with_key_version=CURRENT_KEY_VERSION,
        is_active=True,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return ApifyTokenOut(
        id=row.id,
        label=row.label,
        masked_token=mask_token(token),
        plan_cap_usd=float(row.plan_cap_usd or 5.0),
        is_active=bool(row.is_active),
        created_at=row.created_at,
    )


@router.get("/tokens", response_model=list[ApifyTokenOut])
async def list_tokens(
    db: AsyncSession = Depends(get_db),
    session=Depends(get_current_session),
):
    """List the org's vault tokens. Secrets are masked to the last four chars."""
    rows = await _load_tokens(db, session.org_id)
    out: list[ApifyTokenOut] = []
    for row in rows:
        vault = _to_vault_token(row)
        out.append(
            ApifyTokenOut(
                id=row.id,
                label=row.label,
                masked_token=mask_token(vault.token) if vault else "••••",
                plan_cap_usd=float(row.plan_cap_usd or 5.0),
                is_active=bool(row.is_active),
                created_at=row.created_at,
            )
        )
    return out


@router.patch("/tokens/{token_id}", response_model=ApifyTokenOut)
async def update_token(
    token_id: int,
    payload: ApifyTokenUpdate,
    db: AsyncSession = Depends(get_db),
    session=Depends(get_current_session),
):
    """Adjust a token's plan cap or active flag."""
    row = await _get_token_or_404(db, session.org_id, token_id)
    if payload.plan_cap_usd is not None:
        row.plan_cap_usd = payload.plan_cap_usd
    if payload.is_active is not None:
        row.is_active = payload.is_active
    await db.commit()
    await db.refresh(row)

    vault = _to_vault_token(row)
    return ApifyTokenOut(
        id=row.id,
        label=row.label,
        masked_token=mask_token(vault.token) if vault else "••••",
        plan_cap_usd=float(row.plan_cap_usd or 5.0),
        is_active=bool(row.is_active),
        created_at=row.created_at,
    )


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(
    token_id: int,
    db: AsyncSession = Depends(get_db),
    session=Depends(get_current_session),
):
    """Remove a token from the vault."""
    row = await _get_token_or_404(db, session.org_id, token_id)
    vault = _to_vault_token(row)
    await db.delete(row)
    await db.commit()
    if vault:
        # Drop the cached credit summary so a re-added token is re-checked.
        await ApifyTokenService().invalidate(vault.token)
    return None


# ---------------------------------------------------------------------------
# Credits and cost
# ---------------------------------------------------------------------------


@router.get("/credits")
async def get_credits(
    db: AsyncSession = Depends(get_db),
    session=Depends(get_current_session),
):
    """Per-token remaining Apify credit, served from the 10-minute Redis cache."""
    rows = await _load_tokens(db, session.org_id, active_only=True)
    vault_tokens = [vt for vt in (_to_vault_token(r) for r in rows) if vt]

    summaries = await ApifyTokenService().fetch_credit_summaries(vault_tokens)
    total_remaining = sum(s.remaining_usd for s in summaries if s.is_usable)

    return {
        "tokens": [s.to_dict() for s in summaries],
        "total_remaining_usd": round(total_remaining, 4),
        "usable_token_count": sum(1 for s in summaries if s.is_usable),
    }


@router.get("/cost-estimate")
async def get_cost_estimate(
    db: AsyncSession = Depends(get_db),
    session=Depends(get_current_session),
):
    """Per-campaign monthly Apify cost projection and budget utilization."""
    org_id = session.org_id
    org_settings = await _load_settings(db, org_id)

    result = await db.execute(
        select(Campaign).where(
            Campaign.org_id == org_id, Campaign.status == CampaignStatus.ACTIVE
        )
    )
    campaigns = list(result.scalars().all())

    rows = []
    projected_total = 0.0
    for campaign in campaigns:
        try:
            monthly = estimate_monthly_cost_usd(campaign)
            per_run = estimate_run_cost_usd(campaign)
        except ValueError:
            # Unsupported platform on an existing campaign — show it as free
            # rather than failing the whole estimate.
            monthly, per_run = 0.0, 0.0
        projected_total += monthly
        rows.append(
            {
                "campaign_id": campaign.id,
                "name": campaign.name,
                "platform": getattr(campaign.platform, "value", campaign.platform),
                "poll_frequency_minutes": campaign.poll_frequency_minutes,
                "runs_per_month": round(runs_per_month(campaign), 1),
                "cost_per_run_usd": per_run,
                "estimated_monthly_usd": monthly,
            }
        )

    budget = monthly_budget_usd(org_settings)
    spent = await get_month_spend_usd(org_id)

    return {
        "month": datetime.now(timezone.utc).strftime("%Y-%m"),
        "campaigns": rows,
        "projected_monthly_usd": round(projected_total, 2),
        "spent_month_to_date_usd": round(spent, 4),
        "monthly_budget_usd": budget,
        "budget_utilization_pct": round((spent / budget) * 100, 2) if budget else 0.0,
        "projected_utilization_pct": round((projected_total / budget) * 100, 2)
        if budget
        else 0.0,
    }
