"""Placeholder substitution for the seeded ANGLE/MASTER_CONTEXT prompt corpus.

Moved here (unchanged) from the V6-era ``backend/agent/nodes/generator.py``,
which this package replaces -- reused rather than duplicated per the M2 spec.
"""

# The seeded TryEval corpus (backend/prompts/*_v3.md, ported by backend/seed.py)
# uses single-brace ALL_CAPS placeholders inside ANGLE template bodies, e.g.
# {POST_TEXT}, {SUBREDDIT}, {AUTHOR_NAME} -- plus a literal `[MASTER CONTEXT
# BLOCK]` marker (no braces) for where the platform's master-context text
# goes. `render_angle_template` below is a placeholder-safe str.replace pass
# over these: known placeholders we have real data for get substituted;
# anything else -- including every placeholder we simply don't have data for
# yet (AUTHOR_BIO, HOOK, PILLAR_TAG, ...) -- is left intact rather than
# raising. This is deliberately NOT str.format(): format() requires every
# `{...}` in the string to resolve, so it KeyErrors on all 39 seeded ANGLE
# rows the moment any of these appear.
MASTER_CONTEXT_MARKER = "[MASTER CONTEXT BLOCK]"


def render_angle_template(content: str, values: dict) -> str:
    rendered = content
    master_context = values.get("MASTER_CONTEXT")
    if master_context is not None and MASTER_CONTEXT_MARKER in rendered:
        rendered = rendered.replace(MASTER_CONTEXT_MARKER, master_context)

    for key, value in values.items():
        if value is None:
            continue
        rendered = rendered.replace("{" + key + "}", str(value))

    return rendered
