import re
import logging

from sqlalchemy import select

from backend.database import SessionLocal
from backend.models import Campaign
from backend.agent.state import AgentState

logger = logging.getLogger(__name__)


async def source_post_fetch(state: AgentState) -> AgentState:
    """
    Node 1: SourcePostFetch.

    Deferred to a later milestone: platform-specific fetching now goes through
    Apify actors (see org_apify_tokens / OrgSettings.actor_overrides) rather
    than direct PRAW/API calls, and is wired up by the Apify ingestion router
    being implemented in parallel. This node is a structural placeholder so
    the graph shape survives until that hand-off lands.
    """
    raise NotImplementedError(
        "Source post fetching is implemented via Apify actors in a later milestone."
    )


async def keyword_matcher(state: AgentState) -> AgentState:
    """
    Node 2: KeywordMatcher.
    Checks original_content against campaign keywords.
    Supports exact substring matching and regex patterns (prefixed with regex:).
    """
    campaign_id = state["campaign_id"]
    original_content = state.get("original_content", "")

    async with SessionLocal() as db:
        campaign = await db.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        keywords = campaign.keywords or []  # JSONB array
        matched = []
        pass_filter = False

        for kw in keywords:
            if kw.startswith("regex:"):
                pattern = kw[6:]
                try:
                    if re.search(pattern, original_content, re.IGNORECASE):
                        matched.append(kw)
                        pass_filter = True
                except re.error:
                    logger.warning(f"Invalid regex keyword '{kw}' on campaign {campaign_id}")
            else:
                if kw.lower() in original_content.lower():
                    matched.append(kw)
                    pass_filter = True

        return {
            **state,
            "matched_keywords": matched,
            "pre_filter_pass": pass_filter,
        }
