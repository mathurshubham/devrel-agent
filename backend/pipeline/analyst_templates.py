"""DB-backed prompt-corpus lookups for the Analyst pipeline (PRD V7 §5.5/§5.6).

Mirrors ``backend.pipeline.templates``'s "org-specific row wins over the
system default" model, applied to the ``PromptType.ANALYST`` rows seeded by
``backend/seed.py`` from ``backend/prompts/TryEval_Analyst_Prompts_v3.md``.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PromptTemplate, PromptType

#: Seeded template names (see backend/seed.py::parse_analyst_prompts).
_TEMPLATE_NAMES = {
    "master": "ANALYST-ANALYST_MASTER_CONTEXT",
    "triage": "ANALYST-ANALYST_TRIAGE_FILTER",
    "cluster": "ANALYST-ANALYST_CLUSTERING",
    "stance": "ANALYST-ANALYST_STANCE",
    "quotes": "ANALYST-ANALYST_QUOTES",
    "brief": "ANALYST-ANALYST_INTEL_BRIEF",
}

MASTER_CONTEXT_MARKER = "[ANALYST_MASTER_CONTEXT]"


async def _get_prompt_content(db: AsyncSession, org_id: int, name: str) -> Optional[str]:
    """Org-specific row wins over the system default (``org_id IS NULL``) for
    the same ``name`` -- the "copy on customize" model from PRD V7 §5.5."""
    stmt = (
        select(PromptTemplate)
        .where(
            PromptTemplate.type == PromptType.ANALYST,
            (PromptTemplate.org_id == org_id) | (PromptTemplate.org_id.is_(None)),
            PromptTemplate.name == name,
        )
        .order_by(PromptTemplate.org_id.isnot(None).desc())
    )
    row = (await db.execute(stmt)).scalars().first()
    return row.content if row else None


async def get_analyst_templates(db: AsyncSession, org_id: int) -> dict[str, str]:
    """``{"master", "triage", "cluster", "stance", "quotes", "brief"}`` ->
    rendered template text, with the ``[ANALYST_MASTER_CONTEXT]`` marker
    already inlined into every non-master template. Missing templates come
    back as ``""`` (nodes degrade gracefully rather than crashing)."""
    raw: dict[str, str] = {}
    for key, name in _TEMPLATE_NAMES.items():
        raw[key] = await _get_prompt_content(db, org_id, name) or ""

    master = raw.get("master", "")
    out = {"master": master}
    for key in ("triage", "cluster", "stance", "quotes", "brief"):
        out[key] = raw[key].replace(MASTER_CONTEXT_MARKER, master) if raw[key] else ""
    return out


def render(template: str, values: dict) -> str:
    """Placeholder-safe ``{KEY}`` substitution -- same convention as the
    seeded corpus's ``{POST_TEXT}``/``{PILLAR_TAG}``/etc. placeholders."""
    out = template
    for key, value in values.items():
        if value is None:
            continue
        out = out.replace(key, str(value))
    return out
