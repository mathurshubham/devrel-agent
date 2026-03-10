import praw
import re
import redis.asyncio as redis
import os
from sqlalchemy.future import select
from backend.database import SessionLocal
from backend.models import Campaign, RedditAccount
from backend.utils.encryption import decrypt
from backend.agent.state import AgentState
from backend.utils.praw_token import get_praw_token

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL)

async def reddit_post_fetch(state: AgentState) -> AgentState:
    """
    Node 1: RedditPostFetch
    Fetches a post and its comments using PRAW.
    Respects comment_fetch_limit and max_comment_chars.
    """
    campaign_id = state["campaign_id"]
    post_id = state["reddit_post_id"]

    async with SessionLocal() as db:
        # Fetch campaign and active reddit account for the org
        campaign = await db.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        # Get the first active reddit account for this organization
        result = await db.execute(
            select(RedditAccount).where(
                RedditAccount.org_id == campaign.org_id,
                RedditAccount.is_active == True,
                RedditAccount.deleted_at == None
            ).limit(1)
        )
        reddit_account = result.scalar_one_or_none()
        if not reddit_account:
            raise ValueError(f"No active Reddit account found for org {campaign.org_id}")

        # Initialize PRAW
        # Node 1: Fetches a post using the distributed token lock logic (TRD 4.6)
        token = await get_praw_token(reddit_account.id, reddit_account, redis_client)

        reddit = praw.Reddit(
            client_id=reddit_account.client_id,
            client_secret=decrypt(reddit_account.encrypted_secret),
            access_token=token,
            user_agent="SentinelDevRelAgent/1.0"
        )

        submission = reddit.submission(id=post_id)
        
        # Build original_text
        text_parts = []
        text_parts.append(f"Title: {submission.title}")
        text_parts.append(f"Content: {submission.selftext}")
        
        # Fetch top comments
        submission.comment_sort = "top"
        submission.comments.replace_more(limit=0) # Only top-level for now as per TRD 5.5
        
        comments_taken = 0
        for comment in submission.comments:
            if comments_taken >= campaign.comment_fetch_limit:
                break
            
            # Truncate comment if it exceeds max_comment_chars
            body = comment.body
            if len(body) > campaign.max_comment_chars:
                body = body[:campaign.max_comment_chars] + "..."
            
            text_parts.append(f"Comment by u/{comment.author}: {body}")
            comments_taken += 1
            
        full_text = "\n\n".join(text_parts)
        
        return {
            **state,
            "original_text": full_text,
            "post_url": f"https://reddit.com{submission.permalink}"
        }

async def keyword_matcher(state: AgentState) -> AgentState:
    """
    Node 2: KeywordMatcher
    Checks original_text against campaign keywords.
    Supports exact substring matching and regex patterns (prefixed with regex:).
    """
    campaign_id = state["campaign_id"]
    original_text = state.get("original_text", "")
    
    async with SessionLocal() as db:
        campaign = await db.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        
        keywords = campaign.keywords # This is a JSONB array
        matched = []
        pass_filter = False
        
        for kw in keywords:
            if kw.startswith("regex:"):
                pattern = kw[6:]
                if re.search(pattern, original_text, re.IGNORECASE):
                    matched.append(kw)
                    pass_filter = True
            else:
                if kw.lower() in original_text.lower():
                    matched.append(kw)
                    pass_filter = True
        
        return {
            **state,
            "matched_keywords": matched,
            "pre_filter_pass": pass_filter
        }
