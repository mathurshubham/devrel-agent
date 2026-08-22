"""Org-editable pillar taxonomy for the Analyst pipeline (PRD V7 §5.6).

The MVP (``social-agent``) hardcoded its 10-pillar taxonomy in code
(``services/analyst.py::PILLAR_TOPICS``). V7 moves it to
``OrgSettings.pillar_taxonomy`` (JSONB) so an org can add/rename/retire
pillars without a deploy; ``DEFAULT_PILLAR_TAXONOMY`` below is the seeded
default -- the exact 10-pillar/PRIMARY-SECONDARY split from
``backend/prompts/TryEval_Analyst_Prompts_v3.md``'s ``ANALYST_MASTER_CONTEXT``
section -- used whenever an org hasn't customized it (``pillar_taxonomy`` is
``None``/empty).
"""
from __future__ import annotations

from typing import Any, Optional

#: PRIMARY (1-7): high-priority, surface aggressively.
#: SECONDARY (8-10): surface only when the post is specifically about it.
DEFAULT_PILLAR_TAXONOMY: list[dict[str, str]] = [
    {"tag": "METRICS_ILLUSION", "tier": "PRIMARY"},
    {"tag": "SILENT_REGRESSION", "tier": "PRIMARY"},
    {"tag": "CROSSFUNCTIONAL_OWNERSHIP", "tier": "PRIMARY"},
    {"tag": "CONTINUOUS_QUALITY", "tier": "PRIMARY"},
    {"tag": "RAG_GROUNDEDNESS", "tier": "PRIMARY"},
    {"tag": "JUDGE_RELIABILITY", "tier": "PRIMARY"},
    {"tag": "VIBE_CHECK", "tier": "PRIMARY"},
    {"tag": "AGENT_RELIABILITY", "tier": "SECONDARY"},
    {"tag": "VOICE_CONVERSATION", "tier": "SECONDARY"},
    {"tag": "SAFETY_COMPLIANCE", "tier": "SECONDARY"},
]

#: Pillar tag used when a post genuinely fits none of the taxonomy's pillars.
OTHER_PILLAR = "OTHER"


def get_pillar_taxonomy(org_settings: Any) -> list[dict[str, str]]:
    """The org's pillar taxonomy, or the seeded default when unset."""
    taxonomy = getattr(org_settings, "pillar_taxonomy", None) if org_settings else None
    if isinstance(taxonomy, list) and taxonomy:
        return taxonomy
    return DEFAULT_PILLAR_TAXONOMY


def pillar_tags(taxonomy: list[dict[str, str]]) -> list[str]:
    return [p.get("tag") for p in taxonomy if isinstance(p, dict) and p.get("tag")]


def pillar_tier(taxonomy: list[dict[str, str]], tag: str) -> Optional[str]:
    for p in taxonomy:
        if isinstance(p, dict) and p.get("tag") == tag:
            return p.get("tier")
    return None


def taxonomy_block(taxonomy: list[dict[str, str]]) -> str:
    """Renders the org's taxonomy as a prompt-appendable text block.

    Appended to the clustering prompt so an org-customized taxonomy actually
    steers the LLM's pillar choice, instead of only the illustrative default
    list baked into the seeded ``ANALYST_MASTER_CONTEXT`` prompt text.
    """
    lines = [
        f"- {p.get('tag')} ({p.get('tier', 'PRIMARY')})"
        for p in taxonomy
        if isinstance(p, dict) and p.get("tag")
    ]
    if not lines:
        return ""
    return (
        "\n\nORG PILLAR TAXONOMY (use exactly these tags; ignore any conflicting "
        "example pillars above):\n" + "\n".join(lines)
    )
