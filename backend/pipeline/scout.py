"""Scout layer (PRD V7 §5.3 step 3).

One structured LLM call per campaign poll over that platform's (already
prefiltered) posts. Ports ``social-agent``'s ``run_scout``, replacing its
regex/best-effort JSON scraping with ``response_format`` + Pydantic
validation (one corrective retry, via ``backend.pipeline.llm_transport``).
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.pipeline.llm_transport import structured_completion

logger = logging.getLogger(__name__)

DEFAULT_SCOUT_INSTRUCTIONS = """\
You are an AI Scout for a DevRel team monitoring social platforms.
Your job is to select ALL posts worth a genuine reply and discard the rest.

A post is RELEVANT if it:
- Discusses a topic the org's audience cares about
- Invites genuine discussion, asks a question, or shares an insight worth responding to
- Is written by a practitioner, researcher, or decision-maker (not a job listing or pure ad)

A post is IRRELEVANT if it:
- Is a job posting, hiring ad, or purely promotional content
- Is off-topic or too generic to add value with a reply
- Has no real discussion potential\
"""


class ScoutSelection(BaseModel):
    post_id: str
    angle_name: str
    reply_type: Literal["NEW_COMMENT", "REPLY_TO_COMMENT"] = "NEW_COMMENT"
    target_comment_id: Optional[str] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning: str = ""


class ScoutOutput(BaseModel):
    selections: list[ScoutSelection] = Field(default_factory=list)


def _format_post_for_scout(post: dict) -> str:
    lines = [
        f"POST_ID: {post.get('post_id', 'unknown')} | {str(post.get('content', ''))[:500]}"
    ]
    for c in post.get("top_comments", [])[:5]:
        lines.append(
            f"  COMMENT id={c.get('comment_id')} score={c.get('score', 0)}: "
            f"{str(c.get('content', ''))[:200]}"
        )
    return "\n".join(lines)


def build_scout_prompt(
    instructions: str,
    platform: str,
    angle_names: list[str],
    posts: list[dict],
    hint: str = "",
) -> str:
    posts_text = "\n\n".join(_format_post_for_scout(p) for p in posts)
    angles_text = ", ".join(sorted(angle_names)) if angle_names else "(none configured)"

    return (
        f"{instructions}\n\n"
        f"PLATFORM: {platform}\n\n"
        f"AVAILABLE ANGLES: {angles_text}\n\n"
        f"POSTS (with top comments where available):\n{posts_text}\n\n"
        "For each post worth engaging with, choose the single best angle from "
        "AVAILABLE ANGLES (use its exact name), decide reply_type "
        '("NEW_COMMENT" or "REPLY_TO_COMMENT"), and if REPLY_TO_COMMENT set '
        "target_comment_id to one of that post's listed comment ids (else null). "
        "Assign a confidence between 0.0 and 1.0 and a short one-sentence reasoning.\n\n"
        "Return ONLY a JSON object of this exact shape:\n"
        '{"selections": [{"post_id": "<id>", "angle_name": "<name>", '
        '"reply_type": "NEW_COMMENT", "target_comment_id": null, '
        '"confidence": 0.8, "reasoning": "<why>"}]}\n'
        'If no posts are worth engaging with, return {"selections": []}.'
        + (hint or "")
    )


async def run_scout(
    posts: list[dict],
    angle_names: list[str],
    *,
    platform: str,
    model: str,
    call_kwargs: dict,
    instructions: str = DEFAULT_SCOUT_INSTRUCTIONS,
    hint: str = "",
    acompletion_fn=None,
) -> ScoutOutput:
    """One structured LLM call selecting which posts to draft for, and how."""
    if not posts:
        return ScoutOutput(selections=[])

    prompt = build_scout_prompt(instructions, platform, angle_names, posts, hint)
    parsed, _response = await structured_completion(
        prompt, model, ScoutOutput, call_kwargs, acompletion_fn=acompletion_fn
    )
    return parsed
