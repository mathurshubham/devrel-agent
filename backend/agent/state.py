from typing import TypedDict, List, Optional, Dict, Any
from backend.models import DraftStatus, PlatformEnum


class AgentState(TypedDict):
    """
    Shared state threaded through the LangGraph triage/generation pipeline.

    NOTE: platform-specific fetching (Reddit/LinkedIn/Twitter via Apify actors)
    is implemented in a later milestone (see org_apify_tokens / OrgSettings.
    actor_overrides). The node in agent/nodes/scraper.py is a placeholder for
    that hand-off.
    """
    campaign_id: int
    platform: PlatformEnum
    post_id: str
    url: str
    original_content: str
    matched_keywords: List[str]
    pre_filter_pass: bool
    confidence: float
    triage_reasoning: str
    truncation_applied: bool
    truncation_details: Dict[str, Any]
    ai_draft_text: str
    response_token_count: int
    prompt_template_version: Optional[str]
    final_status: DraftStatus
