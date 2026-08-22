"""Tests for backend/pipeline/draft_format.py.

Ported from social-agent/backend/tests/test_draft_format.py; adapted because
this port has no hardcoded default hook (see the module docstring) and a
generalized, org-agnostic CTA-marker list.
"""

from backend.pipeline.draft_format import (
    append_disclosure,
    clean_draft,
    finalize_draft,
    mentions_product,
)


# --- clean_draft --------------------------------------------------------------


def test_clean_strips_markdown_bold_and_code():
    out = clean_draft("This is **bold** and __also__ and `code`.")
    assert "**" not in out and "__" not in out and "`" not in out
    assert out == "This is bold and also and code."


def test_clean_strips_bullets_and_headings():
    out = clean_draft("# Heading\n- point one\n* point two\n• point three")
    assert out == "Heading\npoint one\npoint two\npoint three"


def test_clean_drops_wrapper_label():
    out = clean_draft("chat_message:\nHello there")
    assert out == "Hello there"


def test_clean_collapses_blank_lines():
    out = clean_draft("Para one.\n\n\n\nPara two.")
    assert out == "Para one.\n\nPara two."


def test_clean_empty_input():
    assert clean_draft("") == ""
    assert clean_draft(None) == ""


# --- finalize_draft -----------------------------------------------------------


def test_finalize_with_no_hook_configured_returns_the_body_unchanged():
    out = finalize_draft("Some reply body.", None)
    assert out == "Some reply body."


def test_finalize_blank_hook_is_treated_as_no_hook():
    out = finalize_draft("Body.", "   ")
    assert out == "Body."


def test_finalize_appends_a_custom_hook_exactly_once():
    hook = "Learn more: https://example.com/x"
    out = finalize_draft("Body.", hook)
    assert out == f"Body.\n\n{hook}"


def test_finalize_is_idempotent():
    hook = "Learn more: https://example.com/x"
    once = finalize_draft("Body.", hook)
    twice = finalize_draft(once, hook)
    assert once == twice


def test_finalize_drops_a_model_invented_link_cta():
    draft = (
        "Great point about evals.\n\n"
        "Check out our platform here: https://example-vendor.com?utm_source=linkedin"
    )
    out = finalize_draft(draft, "Learn more: https://real-hook.example.com")
    assert "example-vendor.com" not in out
    assert out.endswith("Learn more: https://real-hook.example.com")
    assert out.startswith("Great point about evals.")


def test_finalize_drops_a_model_invented_cta_even_with_no_configured_hook():
    draft = "Solid take.\n\nExplore our tool at example.com"
    out = finalize_draft(draft, None)
    assert out == "Solid take."


def test_finalize_empty_body_with_hook_returns_hook_only():
    assert finalize_draft("", "Hook text") == "Hook text"
    assert finalize_draft(None, "Hook text") == "Hook text"


def test_finalize_empty_body_and_no_hook_returns_empty():
    assert finalize_draft("", None) == ""


# --- mentions_product / append_disclosure -------------------------------------


def test_mentions_product_is_case_insensitive_substring_match():
    assert mentions_product("I work on Acme Corp and love it", "acme corp") is True
    assert mentions_product("nothing relevant here", "acme corp") is False


def test_mentions_product_false_for_missing_or_short_name():
    assert mentions_product("some text", None) is False
    assert mentions_product("some text", "a") is False


def test_append_disclosure_adds_the_line_once():
    out = append_disclosure("Some reply mentioning Acme.", "Acme")
    assert out == "Some reply mentioning Acme.\n\n(I work on Acme)"


def test_append_disclosure_is_idempotent():
    once = append_disclosure("Some reply mentioning Acme.", "Acme")
    twice = append_disclosure(once, "Acme")
    assert once == twice


def test_append_disclosure_noop_without_a_product_name():
    text = "Some reply."
    assert append_disclosure(text, None) == text
    assert append_disclosure(text, "") == text
