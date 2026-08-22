"""
Shared org-scoped lookups for OrgLLMConfig / OrgPersona.

Both models use `org_id` as a unique *foreign key* column, not as their
primary key (`id` is). `db.get(OrgLLMConfig, some_org_id)` looks the row up
by its `id` PK, not by `org_id` -- for any org whose `OrgLLMConfig.id` happens
to differ from its `org_id` (i.e. almost always, once more than one org
exists) this either returns another org's BYOK vault entry (a cross-tenant
credential leak) or None. Always go through these helpers instead.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import OrgLLMConfig, OrgPersona


async def get_org_llm_config(db: AsyncSession, org_id: int) -> Optional[OrgLLMConfig]:
    result = await db.execute(select(OrgLLMConfig).where(OrgLLMConfig.org_id == org_id))
    return result.scalar_one_or_none()


async def get_org_persona(db: AsyncSession, org_id: int) -> Optional[OrgPersona]:
    result = await db.execute(select(OrgPersona).where(OrgPersona.org_id == org_id))
    return result.scalar_one_or_none()
