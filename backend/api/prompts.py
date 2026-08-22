from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from backend.database import get_db
from backend.models import PromptTemplate, User, UserRole
from backend.schemas import (
    PromptTemplateCreate, PromptTemplateUpdate, PromptTemplateResponse
)
from backend.utils.auth import get_current_session
from backend.utils.audit import write_audit_log

router = APIRouter(prefix="/api/prompts", tags=["Prompts"])


async def _is_org_admin_or_super(db: AsyncSession, session: dict) -> bool:
    if session.get("role") == UserRole.ADMIN.value:
        return True
    user = await db.get(User, session["user_id"])
    return bool(user and user.role == UserRole.SUPER_ADMIN)


@router.get("", response_model=List[PromptTemplateResponse])
async def list_prompts(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Fetch available prompt templates: both system defaults (org_id IS NULL) and org-specific ones."""
    org_id = session["org_id"]
    stmt = select(PromptTemplate).where(
        (PromptTemplate.org_id == org_id) | (PromptTemplate.org_id.is_(None))
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=PromptTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    payload: PromptTemplateCreate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """Create a new organization-specific prompt template."""
    org_id = session["org_id"]

    new_template = PromptTemplate(
        **payload.model_dump(),
        org_id=org_id,
        version=1
    )
    db.add(new_template)
    await db.flush()
    await db.refresh(new_template)

    await write_audit_log(
        db, org_id,
        action='PROMPT_CREATED',
        details={'prompt_id': new_template.id, 'name': new_template.name},
        user_id=session["user_id"]
    )

    await db.commit()
    return new_template


@router.get("/{id}", response_model=PromptTemplateResponse)
async def get_prompt(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]
    prompt = await db.get(PromptTemplate, id)
    if not prompt or (prompt.org_id is not None and prompt.org_id != org_id):
        raise HTTPException(status_code=404, detail="Prompt template not found")
    return prompt


@router.patch("/{id}", response_model=PromptTemplateResponse)
async def update_prompt(
    id: int,
    payload: PromptTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Update a prompt template, incrementing its version.
    RBAC: system defaults (org_id IS NULL) can only be edited by an org admin
    or platform super admin; org-scoped templates require org membership.
    """
    org_id = session["org_id"]

    prompt = await db.get(PromptTemplate, id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    is_system_default = prompt.org_id is None

    if is_system_default:
        if not await _is_org_admin_or_super(db, session):
            raise HTTPException(status_code=403, detail="Cannot edit system default templates")
    elif prompt.org_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(prompt, key, value)

    prompt.version += 1

    await write_audit_log(
        db, org_id,
        action='PROMPT_UPDATED',
        details={'prompt_id': prompt.id, 'new_version': prompt.version},
        user_id=session["user_id"]
    )

    await db.commit()
    await db.refresh(prompt)
    return prompt


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """RBAC: system defaults cannot be deleted by non-admins."""
    org_id = session["org_id"]

    prompt = await db.get(PromptTemplate, id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    is_system_default = prompt.org_id is None

    if is_system_default:
        if not await _is_org_admin_or_super(db, session):
            raise HTTPException(status_code=403, detail="Cannot delete system default templates")
    elif prompt.org_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    await write_audit_log(
        db, org_id,
        action='PROMPT_DELETED',
        details={'prompt_id': id},
        user_id=session["user_id"]
    )

    await db.delete(prompt)
    await db.commit()
    return None
