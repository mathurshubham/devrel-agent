"""Signal-tier scoring for persisted drafts (PRD V7 §5.7).

Ported from ``social-agent/backend/app/routers/pipeline.py::_compute_signal_tier``,
adapted to V7: watch-list authors come from the org-scoped ``TargetAuthor``
table (the MVP hardcoded a name list in code) rather than a literal constant.
As of M3, the caller (``backend.pipeline.nodes.persist_gate_node``) passes
only Tier 1 ``TargetAuthor`` rows ("always surface" per PRD V7 §5.6/§9) --
Tier 2/3 rows feed the Analyst pipeline's own watch-list weighting instead.

Buyer-persona job-title matching has no dedicated org-scoped table yet in the
V7 schema -- the Analyst pipeline's ``buyer_persona`` tag (PRD §5.6) lives on
per-post classifications, not as an org-editable title/keyword list -- so
this keeps the MVP's hardcoded title list as the default. Engagement
thresholds are likewise the MVP's literal defaults (10 / 50); the PRD notes
these as "org-configurable" but no OrgSettings column exists for them yet.
Both remain known deviations.
"""

from __future__ import annotations

from typing import Iterable, Optional

# TODO(M3): move to an org-scoped BuyerPersona table alongside the Analyst
# pipeline's watch-list/competitor data (PRD §5.6).
BUYER_PERSONA_TITLES = (
    "head of ai", "vp ai", "director ai", "chief ai", "ai lead",
    "product manager", "head of product", "vp product",
    "qa lead", "qa engineer", "quality lead",
    "risk officer", "compliance lead", "governance",
    "cx lead", "contact center", "support automation",
    "founder", "co-founder", "ceo",
)

HIGH_TIER_MIN_ENGAGEMENT = 10
MEDIUM_TIER_MIN_ENGAGEMENT = 50


def compute_signal_tier(post: dict, watch_names: Iterable[str]) -> Optional[str]:
    """Return "HIGH", "MEDIUM", or None based on author/engagement signals."""
    author_name = (post.get("author_name") or post.get("author") or "").strip().lower()
    headline = (post.get("author_headline") or "").lower()
    engagement = int(post.get("engagement_score") or 0)

    watch_lower = [n.strip().lower() for n in watch_names if n and n.strip()]
    if author_name and any(name in author_name for name in watch_lower):
        return "HIGH"
    if any(title in headline for title in BUYER_PERSONA_TITLES) and engagement >= HIGH_TIER_MIN_ENGAGEMENT:
        return "HIGH"
    if engagement >= MEDIUM_TIER_MIN_ENGAGEMENT:
        return "MEDIUM"
    return None
