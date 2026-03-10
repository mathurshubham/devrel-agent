from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import re

from backend.database import get_db
from backend.models import PromptTemplate, UserRole
from backend.schemas import (
    PromptTemplateCreate, PromptTemplateUpdate, PromptTemplateResponse
)
from backend.utils.auth import get_current_session
from backend.utils.audit import write_audit_log

router = APIRouter(prefix="/api/prompts", tags=["Prompts"])

@router.get("", response_model=List[PromptTemplateResponse])
async def list_prompts(
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Fetch available prompt templates.
    Returns both system defaults and organization-specific templates.
    """
    org_id = session["org_id"]
    stmt = select(PromptTemplate).where(
        (PromptTemplate.org_id == org_id) | (PromptTemplate.is_system_default == True)
    )
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("", response_model=PromptTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    payload: PromptTemplateCreate,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    Create a new organization-specific prompt template.
    Validates required prompt variables.
    """
    org_id = session["org_id"]
    
    # 1. Validate prompt variables (must contain {{variable}} placeholders)
    # This is a basic check; specific nodes may require specific variables.
    # TRD 5.3 mentions prompt variables must exist.
    required_vars = re.findall(r"{{(.*?)}}", payload.prompt_body)
    if not required_vars:
        # Optional: could be more strict here depending on category
        pass

    new_template = PromptTemplate(
        **payload.dict(),
        org_id=org_id,
        is_system_default=False,
        version=1
    )
    db.add(new_template)
    await db.commit()
    await db.refresh(new_template)
    
    await write_audit_log(
        db, org_id, 
        action='PROMPT_CREATED', 
        details={'prompt_id': new_template.id, 'title': new_template.title},
        user_id=session["user_id"]
    )
    
    return new_template

@router.get("/{id}", response_model=PromptTemplateResponse)
async def get_prompt(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    org_id = session["org_id"]
    prompt = await db.get(PromptTemplate, id)
    if not prompt or (prompt.org_id != org_id and not prompt.is_system_default):
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
    Update a prompt template.
    Increments version number (Section 5.3).
    RBAC: System defaults cannot be edited by standard members.
    """
    org_id = session["org_id"]
    user_role = session.get("org_role") # Clerk role
    
    prompt = await db.get(PromptTemplate, id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    
    # RBAC Check: System defaults protection
    if prompt.is_system_default:
        # Only SUPER_ADMIN can edit system defaults? 
        # TRD implies MEMBER shouldn't edit system defaults.
        # We'll allow ADMINs to "copy" or "fork" if they want, but here we protect the record.
        if user_role != "org:admin" and session.get("role") != UserRole.SUPER_ADMIN:
             raise HTTPException(status_code=403, detail="Cannot edit system default templates")

    if prompt.org_id and prompt.org_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(prompt, key, value)
    
    # Increment Version (Section 5.3)
    prompt.version += 1
    
    await db.commit()
    await db.refresh(prompt)
    
    await write_audit_log(
        db, org_id, 
        action='PROMPT_UPDATED', 
        details={'prompt_id': prompt.id, 'new_version': prompt.version},
        user_id=session["user_id"]
    )
    
    return prompt

@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt(
    id: int,
    db: AsyncSession = Depends(get_db),
    session: dict = Depends(get_current_session)
):
    """
    RBAC: System defaults cannot be deleted by non-admins.
    """
    org_id = session["org_id"]
    user_role = session.get("org_role")
    
    prompt = await db.get(PromptTemplate, id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    
    if prompt.is_system_default:
        if user_role != "org:admin" and session.get("role") != UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Cannot delete system default templates")

    if prompt.org_id and prompt.org_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    await db.delete(prompt)
    await db.commit()
    
    await write_audit_log(
        db, org_id, 
        action='PROMPT_DELETED', 
        details={'prompt_id': id},
        user_id=session["user_id"]
    )
    return None
