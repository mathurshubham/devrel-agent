"""Realistic raw actor payloads, trimmed from real runs.

The LinkedIn samples come from ``social-agent/docs/apify-actor-reference.md``
(apimaestro keyword-search actor); the Reddit and Twitter samples mirror the
shapes the automation-lab and kaitoeasyapi actors emit.
"""

# --- LinkedIn (apimaestro/linkedin-posts-search-scraper-no-cookies) ---------

LINKEDIN_JOB_POST = {
    "activity_id": "7450541901457526784",
    "post_url": "https://www.linkedin.com/posts/vivekuday_activity-7450541901457526784-EYni",
    "text": "Have you been thinking about how AI is reshaping product experiences?",
    "full_urn": "urn:li:activity:7450541901457526784",
    "author": {
        "name": "Vivek Uday",
        "headline": "Product Analytics Leader @ Airbnb | Payments & Conversational AI Products",
        "profile_id": "56364851",
        "profile_url": "https://www.linkedin.com/in/vivekuday",
        "image_url": "",
    },
    "stats": {
        "total_reactions": 33,
        "comments": 5,
        "shares": 1,
        "reactions": [{"type": "LIKE", "count": 33}],
    },
    "posted_at": {
        "display_text": "1w",
        "date": "2026-04-16 15:53:33",
        "timestamp": 1776347613682,
    },
    "hashtags": [],
    "content": {
        "type": "job",
        "title": "Lead Advanced Analytics, Digital & AI Products",
        "description": "Bengaluru, Karnataka, India (Hybrid)",
        "subtitle": "Job by Airbnb",
    },
    "is_reshare": False,
    "search_input": "LLM evaluations",
}

LINKEDIN_ARTICLE_POST = {
    "activity_id": "7451013654805651456",
    "post_url": "https://www.linkedin.com/posts/shakunvohra_activity-7451013654805651456-YKX5",
    "text": 'The $812 court case. The $1 Tahoe. The $100B market-cap drop.',
    "full_urn": "urn:li:ugcPost:7451013654352728064",
    "author": {
        "name": "Shakun Vohra",
        "headline": "AI Innovation Leader | Engineering Executive",
        "profile_url": "https://www.linkedin.com/in/shakunvohra",
    },
    "stats": {
        "total_reactions": 25,
        "comments": 3,
        "shares": 1,
        "reactions": [{"type": "LIKE", "count": 23}, {"type": "PRAISE", "count": 2}],
    },
    "posted_at": {
        "display_text": "1w",
        "date": "2026-04-17 23:08:08",
        "timestamp": 1776460088445,
    },
    "content": {"type": "article", "article": {"title": "LLM as a Judge — or Jury?"}},
    "is_reshare": False,
}

LINKEDIN_TEXT_POST = {
    "activity_id": "7450382035078131712",
    "post_url": "https://www.linkedin.com/posts/bufan-shen-832475151_activity-7450382035078131712-A5RC",
    "text": "I'm looking for someone strong in LLM evaluation.",
    "full_urn": "urn:li:activity:7450382035078131712",
    "author": {
        "name": "bufan shen",
        "headline": "Agent Evaluation & Human Decision Research at Shopint",
        "profile_url": "https://www.linkedin.com/in/bufan-shen-832475151",
    },
    "stats": {"total_reactions": 5, "comments": 2, "shares": 0},
    "posted_at": {"display_text": "1w", "date": "2026-04-16 05:18:18", "timestamp": 1776309498567},
    "content": {"type": "text", "text": "I'm looking for someone strong in LLM evaluation."},
    "is_reshare": False,
}

#: Different actor: flat engagement fields, bare numeric id, relative-only date.
LINKEDIN_LEGACY_SHAPE_POST = {
    "id": "7400000000000000001",
    "commentary": "A post from an actor that uses the older flat shape.",
    "actor": {
        "fullName": "Dana Legacy",
        "subtitle": "Staff Engineer",
        "publicId": "dana-legacy",
    },
    "numLikes": 12,
    "numComments": 4,
    "numShares": 2,
    "posted_at": {"display_text": "21m"},
}

LINKEDIN_NO_ID_POST = {"text": "orphan item with no identifier", "author": {"name": "Nobody"}}

LINKEDIN_SAMPLE = [
    LINKEDIN_JOB_POST,
    LINKEDIN_ARTICLE_POST,
    LINKEDIN_TEXT_POST,
    LINKEDIN_LEGACY_SHAPE_POST,
    LINKEDIN_NO_ID_POST,
]


# --- Reddit (automation-lab/reddit-scraper) ---------------------------------

REDDIT_SAMPLE = [
    {
        "type": "post",
        "id": "1abc234",
        "title": "How are you evaluating your RAG pipeline?",
        "selfText": "We keep shipping regressions. What does your eval stack look like?",
        "author": "eval_curious",
        "url": "https://reddit.com/r/LLMDevs/comments/1abc234/how_are_you_evaluating/",
        "upVotes": 128,
        "numberOfComments": 2,
        "createdAt": "2026-08-01T12:00:00.000Z",
        "communityName": "r/LLMDevs",
    },
    {
        "type": "comment",
        "id": "c_001",
        "postId": "1abc234",
        "author": "ragged_edge",
        "body": "Golden set plus an LLM judge, re-run on every prompt change.",
        "score": 42,
        "permalink": "/r/LLMDevs/comments/1abc234/comment/c_001/",
    },
    {
        "type": "comment",
        "id": "c_002",
        "postId": "1abc234",
        "author": "skeptic99",
        "body": "LLM judges drift. We still spot-check by hand.",
        "score": 7,
        "permalink": "/r/LLMDevs/comments/1abc234/comment/c_002/",
    },
    {
        "type": "comment",
        "id": "c_003",
        "postId": "orphaned_post_id",
        "author": "lost",
        "body": "comment whose parent post is not in the dataset",
        "score": 1,
    },
    {
        "type": "post",
        "id": "1def567",
        "title": "Link post with no body",
        "selfText": "",
        "author": "linker",
        "url": "https://example.com/article",
        "upVotes": 3,
        "numberOfComments": 0,
        "createdAt": "2026-08-02T09:30:00.000Z",
    },
    {"type": "post", "title": "post with no id, must be skipped", "author": "ghost"},
]


# --- Twitter (kaitoeasyapi/twitter-x-data-tweet-scraper) --------------------

TWITTER_SAMPLE = [
    {
        "id": "1799999999999999999",
        "text": "Hot take: your eval suite is your real product spec.",
        "url": "https://twitter.com/evalpilled/status/1799999999999999999",
        "createdAt": "Tue Aug 05 14:21:09 +0000 2026",
        "likeCount": 210,
        "replyCount": 18,
        "retweetCount": 34,
        "quoteCount": 6,
        "author": {
            "userName": "evalpilled",
            "name": "Eval Pilled",
            "description": "Shipping LLM systems that do not embarrass us.",
            "url": "https://twitter.com/evalpilled",
        },
    },
    {
        "id": "1788888888888888888",
        "text": "Anyone using DeepEval in CI?",
        "createdAt": "Mon Aug 04 08:02:41 +0000 2026",
        "likeCount": 4,
        "replyCount": 2,
        "retweetCount": 0,
        "author": {"screen_name": "ci_curious", "displayName": "CI Curious"},
    },
    {"text": "tweet with no id, must be skipped", "author": {"userName": "ghost"}},
]
