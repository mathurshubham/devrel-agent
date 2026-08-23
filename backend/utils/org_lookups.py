"""
Shared org-scoped lookups for OrgLLMConfig / OrgPersona.

Both models use `org_id` as a unique *foreign key* column, not as their
primary key (`id` is). `db.get(OrgLLMConfig, some_org_id)` looks the row up
by its `id` PK, not by `org_id` -- for any org whose `OrgLLMConfig.id` happens
to differ from its `org_id` (i.e. almost always, once more than one org
exists) this either returns another org's BYOK vault entry (a cross-tenant
credential leak) or None. Always go through these helpers instead.
"""
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import OrgApifyToken, OrgLLMConfig, OrgPersona, OrgSettings

logger = logging.getLogger(__name__)


async def get_org_llm_config(db: AsyncSession, org_id: int) -> Optional[OrgLLMConfig]:
    result = await db.execute(select(OrgLLMConfig).where(OrgLLMConfig.org_id == org_id))
    return result.scalar_one_or_none()


async def get_org_persona(db: AsyncSession, org_id: int) -> Optional[OrgPersona]:
    result = await db.execute(select(OrgPersona).where(OrgPersona.org_id == org_id))
    return result.scalar_one_or_none()


async def get_org_settings(db: AsyncSession, org_id: int) -> Optional[OrgSettings]:
    """Same ``org_id``-is-not-the-PK pitfall as the two lookups above."""
    result = await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
    return result.scalar_one_or_none()


async def get_active_apify_vault_tokens(db: AsyncSession, org_id: int) -> list:
    """Decrypted, active ``OrgApifyToken`` rows as ``VaultToken``s.

    Lives here (not ``backend.ingestion.tokens``) because it touches the DB
    and decryption -- the ingestion layer stays DB-free by design.
    """
    from backend.ingestion.tokens import VaultToken
    from backend.utils.encryption import decrypt

    result = await db.execute(
        select(OrgApifyToken).where(
            OrgApifyToken.org_id == org_id, OrgApifyToken.is_active.is_(True)
        )
    )
    rows = result.scalars().all()

    tokens: list[VaultToken] = []
    for row in rows:
        try:
            plaintext = decrypt(row.encrypted_token, row.encrypted_with_key_version or 1)
        except Exception:
            logger.exception("Could not decrypt Apify token id=%s for org %s", row.id, org_id)
            continue
        tokens.append(
            VaultToken(
                token=plaintext,
                token_id=row.id,
                label=row.label,
                plan_cap_usd=float(row.plan_cap_usd or 5.0),
            )
        )
    return tokens
