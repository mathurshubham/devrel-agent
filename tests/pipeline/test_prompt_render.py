"""Placeholder substitution against real seeded ANGLE templates.

Loads directly from backend/prompts/*_v3.md via backend.seed's own parser
(no DB needed) so this test exercises render_angle_template against the
actual prompt corpus rather than a hand-rolled fixture string.
"""

import os

from backend.pipeline.prompt_render import MASTER_CONTEXT_MARKER, render_angle_template
from backend.seed import PROMPTS_DIR, parse_platform_markdown


def _load_angles(filename: str, platform_slug: str):
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path) as f:
        content = f.read()
    return parse_platform_markdown(content, platform_slug)


def test_reddit_master_context_and_angles_parse_from_the_real_corpus():
    master_context, angles = _load_angles("TryEval_Reddit_Reply_Prompts_v3.md", "REDDIT")
    assert master_context and len(master_context) > 100
    assert len(angles) >= 3
    names = [a["name"] for a in angles]
    assert any("Metrics Illusion" in n for n in names)


def test_render_substitutes_master_context_marker_for_reddit_angle_1():
    master_context, angles = _load_angles("TryEval_Reddit_Reply_Prompts_v3.md", "REDDIT")
    angle = next(a for a in angles if "Metrics Illusion" in a["name"])
    assert MASTER_CONTEXT_MARKER in angle["content"]

    rendered = render_angle_template(
        angle["content"],
        {
            "MASTER_CONTEXT": master_context,
            "SUBREDDIT": "MachineLearning",
            "POST_TITLE": "We hit 95% on our eval benchmark",
            "POST_BODY": "Our new model scored 95% aggregate accuracy.",
            "PARENT_COMMENT": "",
        },
    )

    assert MASTER_CONTEXT_MARKER not in rendered
    assert master_context[:60] in rendered  # the real master-context text landed in place
    assert "{SUBREDDIT}" not in rendered
    assert "MachineLearning" in rendered
    assert "{POST_TITLE}" not in rendered
    assert "We hit 95% on our eval benchmark" in rendered
    assert "{POST_BODY}" not in rendered
    # PARENT_COMMENT was explicitly provided as "" -- it must still resolve
    # (not be left as a literal placeholder).
    assert "{PARENT_COMMENT}" not in rendered


def test_render_leaves_unresolvable_placeholders_intact_rather_than_raising():
    angle_body = "Hello {POST_TEXT}, brought to you by {AUTHOR_BIO} and {HOOK}."
    rendered = render_angle_template(angle_body, {"POST_TEXT": "world"})
    assert rendered == "Hello world, brought to you by {AUTHOR_BIO} and {HOOK}."


def test_render_skips_none_valued_placeholders():
    angle_body = "Reply to {PARENT_COMMENT} about {POST_TEXT}"
    rendered = render_angle_template(angle_body, {"PARENT_COMMENT": None, "POST_TEXT": "the topic"})
    # None means "no value available" -- left untouched rather than
    # stringified to the literal word "None".
    assert "{PARENT_COMMENT}" in rendered
    assert "None" not in rendered
    assert "the topic" in rendered


def test_render_against_a_second_platforms_angle_linkedin():
    master_context, angles = _load_angles("TryEval_LinkedIn_Reply_Prompts_v3.md", "LINKEDIN")
    assert angles, "expected at least one LinkedIn angle in the seeded corpus"
    angle = angles[0]

    rendered = render_angle_template(
        angle["content"],
        {"MASTER_CONTEXT": master_context or "", "POST_TEXT": "A LinkedIn post about evals."},
    )
    if MASTER_CONTEXT_MARKER in angle["content"]:
        assert MASTER_CONTEXT_MARKER not in rendered
    if "{POST_TEXT}" in angle["content"]:
        assert "A LinkedIn post about evals." in rendered
        assert "{POST_TEXT}" not in rendered
