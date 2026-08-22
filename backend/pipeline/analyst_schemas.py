"""Structured-output schemas for the Analyst pipeline's per-post LLM steps
(PRD V7 §5.6). Field shapes mirror the seeded prompt corpus's documented
JSON output exactly (``backend/prompts/TryEval_Analyst_Prompts_v3.md``), so
that ``backend.pipeline.llm_transport.structured_completion`` can validate
the LLM's response directly instead of best-effort regex JSON scraping.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

VALID_STANCES = {"PROBLEM_PRESENT", "PROBLEM_CRITIQUED", "NEUTRAL"}


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    relevance_score: Optional[int] = None
    signal_score: Optional[int] = None
    buyer_persona: str = "OTHER"
    watch_list_tier: str = "NONE"
    decision: Literal["PROCESS_FULL", "PROCESS_LIGHT", "SKIP"] = "PROCESS_LIGHT"
    reason_short: str = ""


class ClusterResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary_pillar: str = "OTHER"
    secondary_pillars: list[str] = Field(default_factory=list)
    tier_summary: str = "NO_PILLAR_FIT"
    topic_specific: bool = False
    rationale: str = ""


class StanceResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stance: str = "NEUTRAL"
    #: The seeded prompt asks for a categorical HIGH/MEDIUM/LOW; a model may
    #: still return a bare number, so this stays a string and gets converted
    #: by ``confidence_to_float`` rather than a strict enum.
    confidence: str = "MEDIUM"
    evidence_quote: str = ""
    rationale: str = ""


class QuoteItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = ""
    angle: Optional[str] = None
    tier: Optional[str] = None
    why_it_matters: Optional[str] = None


class QuotesResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    quotes: list[QuoteItem] = Field(default_factory=list)


def confidence_to_float(value) -> float:
    """Maps the v3 categorical confidence (HIGH/MEDIUM/LOW) -- or a raw
    number -- to a float. Ported from ``social-agent``'s
    ``AnalystService._confidence_to_float``."""
    if isinstance(value, (int, float)):
        f = float(value)
        return f if f <= 1.0 else min(f / 100.0, 1.0)
    s = str(value or "").upper().strip()
    return {"HIGH": 0.9, "MEDIUM": 0.6, "MED": 0.6, "LOW": 0.3}.get(s, 0.5)
