import json

from backend.pipeline.scout import (
    DEFAULT_SCOUT_INSTRUCTIONS,
    ScoutOutput,
    build_scout_prompt,
    run_scout,
)


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeResponse:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": _FakeMessage(content)})()]


def _fn_returning(payload: str):
    async def _fn(**kwargs):
        return _FakeResponse(payload)

    return _fn


POSTS = [
    {"post_id": "p1", "content": "We hit 95% on our eval benchmark, feels great", "top_comments": []},
    {
        "post_id": "p2",
        "content": "Hiring: Senior DevRel Engineer, apply now",
        "top_comments": [
            {"comment_id": "c1", "content": "Not interested", "score": 3, "author": "x"},
        ],
    },
]


def test_build_scout_prompt_includes_platform_angles_and_posts():
    prompt = build_scout_prompt(
        DEFAULT_SCOUT_INSTRUCTIONS, "REDDIT", ["REDDIT-ANGLE-1: Metrics Illusion"], POSTS
    )
    assert "PLATFORM: REDDIT" in prompt
    assert "REDDIT-ANGLE-1: Metrics Illusion" in prompt
    assert "p1" in prompt and "p2" in prompt
    assert "COMMENT id=c1" in prompt


def test_build_scout_prompt_appends_the_hint_when_present():
    prompt = build_scout_prompt(
        DEFAULT_SCOUT_INSTRUCTIONS, "REDDIT", ["angle-a"], POSTS, hint="\n\nHINT: prefer angle-a"
    )
    assert prompt.endswith("HINT: prefer angle-a")


async def test_run_scout_with_no_posts_short_circuits_without_calling_the_llm():
    calls = {"n": 0}

    async def _fn(**kwargs):
        calls["n"] += 1
        return _FakeResponse("{}")

    result = await run_scout([], ["a"], platform="REDDIT", model="m", call_kwargs={}, hint="")
    assert result.selections == []
    assert calls["n"] == 0


async def test_run_scout_parses_a_valid_selection():
    payload = json.dumps(
        {
            "selections": [
                {
                    "post_id": "p1",
                    "angle_name": "REDDIT-ANGLE-1: Metrics Illusion",
                    "reply_type": "NEW_COMMENT",
                    "target_comment_id": None,
                    "confidence": 0.82,
                    "reasoning": "on-topic eval discussion",
                }
            ]
        }
    )
    result = await run_scout(
        POSTS,
        ["REDDIT-ANGLE-1: Metrics Illusion"],
        platform="REDDIT",
        model="m",
        call_kwargs={},
        acompletion_fn=_fn_returning(payload),
    )
    assert len(result.selections) == 1
    sel = result.selections[0]
    assert sel.post_id == "p1"
    assert sel.angle_name == "REDDIT-ANGLE-1: Metrics Illusion"
    assert sel.confidence == 0.82


async def test_run_scout_returns_empty_selections_when_the_model_declines():
    result = await run_scout(
        POSTS,
        ["some-angle"],
        platform="REDDIT",
        model="m",
        call_kwargs={},
        acompletion_fn=_fn_returning(json.dumps({"selections": []})),
    )
    assert result.selections == []


async def test_scout_output_schema_rejects_bad_reply_type():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ScoutOutput.model_validate(
            {
                "selections": [
                    {"post_id": "p1", "angle_name": "a", "reply_type": "SOMETHING_ELSE"}
                ]
            }
        )


async def test_scout_output_schema_defaults():
    parsed = ScoutOutput.model_validate({"selections": [{"post_id": "p1", "angle_name": "a"}]})
    sel = parsed.selections[0]
    assert sel.reply_type == "NEW_COMMENT"
    assert sel.target_comment_id is None
    assert sel.confidence == 0.5
    assert sel.reasoning == ""


async def test_scout_output_empty_selections_when_nothing_qualifies():
    parsed = ScoutOutput.model_validate({"selections": []})
    assert parsed.selections == []
