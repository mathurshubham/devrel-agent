"""Strategist layer (PRD V7 §5.3 step 5).

Ports ``social-agent``'s batched strategist: 4 posts per LLM call, per-post
fallback for anything missing from a batch response. The concurrency /
fresh-session-per-batch orchestration lives in ``backend.pipeline.nodes``
(the regression this pins is a DB-session bug, not an LLM-call bug); this
module only makes the LLM calls.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from backend.pipeline.llm_transport import extract_usage

logger = logging.getLogger(__name__)

BATCH_SIZE = 4
BATCH_CONCURRENCY = 2

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

_BATCH_FORMATTING_RULES = (
    "FORMATTING for every draft: short plain-text paragraphs separated by a single "
    "blank line. No markdown, no bold, no bullet lists, no headings. Do NOT add any "
    "call-to-action, link, sign-off, or promotional line -- that is appended "
    "automatically afterward."
)


def _post_block(index: int, item: dict) -> str:
    comment_block = ""
    if item.get("reply_type") == "REPLY_TO_COMMENT" and item.get("target_comment"):
        tc = item["target_comment"]
        comment_block = (
            f"\nREPLY TO THIS SPECIFIC COMMENT -- engage it directly:\n"
            f"Author: {tc.get('author', 'Unknown')}\n"
            f"Comment: {tc.get('content', '')}\n"
        )
    return (
        f"--- POST {index} (id: {item['post_id']}) ---\n"
        f"{item['prompt']}\n"
        f"{comment_block}"
    )


async def run_strategist_batch(
    items: list[dict],
    model: str,
    call_kwargs: dict,
    *,
    acompletion_fn=None,
    usage_sink: Optional[list] = None,
) -> dict[str, str]:
    """Draft replies for up to ``BATCH_SIZE`` posts in a single LLM call.

    Each item needs ``post_id`` and ``prompt`` (the fully-rendered per-post
    angle instructions, already including that post's master-context block);
    optionally ``reply_type``/``target_comment`` for a comment callout.
    Returns ``{post_id: draft_text}``; missing keys mean the caller should
    fall back to a per-post call. Never raises -- a parse/call failure
    yields an empty dict so every item falls back.

    ``usage_sink``, if given, gets one ``{"prompt_tokens", "completion_tokens"}``
    dict appended for this call's actual usage (when the response carries
    one) -- so the caller can meter this batch call into the org's recorded
    LLM spend even though persist_gate's own cost check never sees it.
    """
    if acompletion_fn is None:
        from litellm import acompletion as acompletion_fn

    prompt = (
        f"Draft replies to the {len(items)} posts below. Each reply must follow the "
        "tone rules embedded in its own instructions.\n"
        f"{_BATCH_FORMATTING_RULES}\n"
        "Return ONLY a JSON array -- one object per post, SAME ORDER as input:\n"
        '[{"post_id": "<id>", "draft": "<reply text>"}]\n\n'
        + "\n\n".join(_post_block(i, item) for i, item in enumerate(items, 1))
    )

    try:
        response = await acompletion_fn(
            model=model, messages=[{"role": "user", "content": prompt}], **call_kwargs
        )
        if usage_sink is not None:
            usage = extract_usage(response)
            if usage is not None:
                usage_sink.append(usage)
        content = response.choices[0].message.content or ""
        match = _JSON_ARRAY_RE.search(content)
        if not match:
            return {}
        results = json.loads(match.group(0))
        if not isinstance(results, list):
            return {}
        return {
            r["post_id"]: r["draft"]
            for r in results
            if isinstance(r, dict) and "post_id" in r and "draft" in r
        }
    except Exception as exc:
        logger.warning("run_strategist_batch failed, falling back per-post: %s", exc)
        return {}


async def run_strategist_single(
    item: dict,
    model: str,
    call_kwargs: dict,
    *,
    acompletion_fn=None,
    usage_sink: Optional[list] = None,
) -> str:
    """Per-post fallback draft call for a post missing from its batch response."""
    if acompletion_fn is None:
        from litellm import acompletion as acompletion_fn

    comment_block = ""
    if item.get("reply_type") == "REPLY_TO_COMMENT" and item.get("target_comment"):
        tc = item["target_comment"]
        comment_block = (
            f"\nTHE SPECIFIC COMMENT TO REPLY TO:\nAuthor: {tc.get('author', 'Unknown')}\n"
            f"Content: {tc.get('content', '')}\n\n"
            "Your reply should engage THIS comment directly, not just the post.\n"
        )

    prompt = (
        f"{item['prompt']}\n{comment_block}\n"
        "Write the best possible reply for this post, following all tone rules above.\n\n"
        f"{_BATCH_FORMATTING_RULES}"
    )
    response = await acompletion_fn(
        model=model, messages=[{"role": "user", "content": prompt}], **call_kwargs
    )
    if usage_sink is not None:
        usage = extract_usage(response)
        if usage is not None:
            usage_sink.append(usage)
    return (response.choices[0].message.content or "").strip()
