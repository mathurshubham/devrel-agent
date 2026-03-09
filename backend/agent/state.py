from typing import TypedDict, List, Optional, Dict, Any
from backend.models import DraftStatus

class AgentState(TypedDict):
    campaign_id: int
    reddit_post_id: str
    post_url: str
    original_text: str
    matched_keywords: List[str]
    pre_filter_pass: bool
    confidence_score: float
    triage_reasoning: str
    truncation_applied: bool
    truncation_details: Dict[str, Any]
    ai_draft_text: str
    model_payload_token_count: int
    final_status: DraftStatus
