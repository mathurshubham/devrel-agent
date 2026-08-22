"""Post-processing for strategist reply drafts (PRD V7 §5.3 step 6, "finalize").

Ported from ``social-agent/backend/app/services/draft_format.py``. The
markdown-stripping and paragraph-normalization logic (``clean_draft``) is
generic and carried over as-is. Two things are deliberately NOT ported
verbatim, because they were specific to the sibling's own (unrelated)
product:

- The CTA-marker list used to drop a model-invented call-to-action line is
  generalized here to "looks like a link or a promotional sign-off" instead
  of literal ``tryeval.com`` strings.
- There is no hardcoded default hook. When an org has not configured
  ``OrgSettings.reply_hook``, ``finalize_draft`` appends nothing -- the V7
  reply-hook presets (Banner / Soft / custom / none) are an org choice, not
  a shipped advertisement.
"""

import re

# Lines that look like an LLM-invented CTA/link -- dropped before the
# configured hook is appended so a draft never carries two calls-to-action.
_CTA_MARKERS = (
    "http://", "https://", "www.",
    "explore ", "try our", "try out ", "check out our",
    "learn more at", "sign up at", "visit us at",
)

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_LEADING_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_LEADING_BULLET_RE = re.compile(r"^\s*[-*•]\s+")
_WRAPPER_LABEL_RE = re.compile(r"^\s*(chat_message|message|reply|draft)\s*:\s*$", re.IGNORECASE)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def clean_draft(text: str) -> str:
    """Strip markdown artifacts and normalize spacing to plain paragraphs."""
    if not text:
        return ""

    # Remove markdown emphasis / inline code, keeping the inner text.
    text = _BOLD_RE.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)

    cleaned_lines = []
    for line in text.split("\n"):
        if _WRAPPER_LABEL_RE.match(line):
            continue  # drop stray "chat_message:" style labels
        line = _LEADING_HEADING_RE.sub("", line)
        line = _LEADING_BULLET_RE.sub("", line)
        cleaned_lines.append(line.rstrip())

    text = "\n".join(cleaned_lines)
    # Collapse 3+ newlines to a single blank line between paragraphs.
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def finalize_draft(text: str, hook: str | None) -> str:
    """Clean the draft, drop any LLM-added CTA, and append the configured hook.

    ``hook`` is ``OrgSettings.reply_hook``. Blank/``None`` means the org has
    not configured one -- append nothing (see module docstring). Idempotent:
    re-running never duplicates the hook.
    """
    hook = (hook or "").strip()
    body = clean_draft(text)

    # Drop any pre-existing CTA/link lines the model may have added.
    kept = [
        line for line in body.split("\n")
        if not any(marker in line.lower() for marker in _CTA_MARKERS)
    ]
    body = "\n".join(kept)
    body = _MULTI_BLANK_RE.sub("\n\n", body).strip()

    if not hook:
        return body
    if not body:
        return hook
    if body.endswith(hook):
        return body
    return f"{body}\n\n{hook}"


def append_disclosure(text: str, product_name: str | None) -> str:
    """Append a conservative Reddit disclosure line when the draft names the product.

    PRD V7 §5.8: disclosure defaults on for Reddit when the draft references
    the product. There is no dedicated "product name" setting in the V7
    schema, so ``product_name`` is the org's display name (``Organization.
    name``) -- the caller only invokes this when that name already appears
    in the draft text. Idempotent.
    """
    if not product_name:
        return text
    disclosure = f"(I work on {product_name})"
    if disclosure.lower() in text.lower():
        return text
    if not text:
        return disclosure
    return f"{text}\n\n{disclosure}"


def mentions_product(text: str, product_name: str | None) -> bool:
    """Conservative check: does the draft name the org by its display name."""
    if not product_name or len(product_name.strip()) < 2:
        return False
    return product_name.strip().lower() in (text or "").lower()
