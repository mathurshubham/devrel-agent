import json

from backend.pipeline.strategist import run_strategist_batch, run_strategist_single


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeResponse:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": _FakeMessage(content)})()]


def _fn_returning(*payloads):
    calls = {"n": 0}

    async def _fn(**kwargs):
        i = calls["n"]
        calls["n"] += 1
        payload = payloads[min(i, len(payloads) - 1)]
        if isinstance(payload, Exception):
            raise payload
        return _FakeResponse(payload)

    _fn.calls = calls
    return _fn


ITEMS = [
    {"post_id": "p1", "prompt": "Angle instructions for p1", "reply_type": "NEW_COMMENT"},
    {"post_id": "p2", "prompt": "Angle instructions for p2", "reply_type": "NEW_COMMENT"},
    {
        "post_id": "p3",
        "prompt": "Angle instructions for p3",
        "reply_type": "REPLY_TO_COMMENT",
        "target_comment": {"author": "someone", "content": "a sharp take"},
    },
]


# --- run_strategist_batch ------------------------------------------------------


async def test_batch_returns_a_draft_per_post_in_order():
    payload = json.dumps(
        [
            {"post_id": "p1", "draft": "draft for p1"},
            {"post_id": "p2", "draft": "draft for p2"},
            {"post_id": "p3", "draft": "draft for p3"},
        ]
    )
    fn = _fn_returning(payload)
    result = await run_strategist_batch(ITEMS, "model-x", {}, acompletion_fn=fn)
    assert result == {"p1": "draft for p1", "p2": "draft for p2", "p3": "draft for p3"}


async def test_batch_with_a_missing_post_still_returns_what_it_has():
    payload = json.dumps([{"post_id": "p1", "draft": "draft for p1"}])
    fn = _fn_returning(payload)
    result = await run_strategist_batch(ITEMS, "model-x", {}, acompletion_fn=fn)
    assert result == {"p1": "draft for p1"}
    assert "p2" not in result and "p3" not in result


async def test_batch_returns_empty_dict_on_unparseable_response():
    fn = _fn_returning("not a json array at all")
    result = await run_strategist_batch(ITEMS, "model-x", {}, acompletion_fn=fn)
    assert result == {}


async def test_batch_returns_empty_dict_when_the_call_raises():
    fn = _fn_returning(RuntimeError("provider outage"))
    result = await run_strategist_batch(ITEMS, "model-x", {}, acompletion_fn=fn)
    assert result == {}


async def test_batch_prompt_includes_the_target_comment_callout():
    captured = {}

    async def _fn(model, messages, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return _FakeResponse(json.dumps([{"post_id": "p3", "draft": "ok"}]))

    await run_strategist_batch(ITEMS, "model-x", {}, acompletion_fn=_fn)
    assert "REPLY TO THIS SPECIFIC COMMENT" in captured["prompt"]
    assert "a sharp take" in captured["prompt"]


# --- run_strategist_single (per-post fallback) --------------------------------


async def test_single_fallback_returns_stripped_text():
    fn = _fn_returning("  a plain reply  ")
    text = await run_strategist_single(ITEMS[0], "model-x", {}, acompletion_fn=fn)
    assert text == "a plain reply"


async def test_single_fallback_includes_the_comment_block_for_reply_to_comment():
    captured = {}

    async def _fn(model, messages, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return _FakeResponse("ok")

    await run_strategist_single(ITEMS[2], "model-x", {}, acompletion_fn=_fn)
    assert "THE SPECIFIC COMMENT TO REPLY TO" in captured["prompt"]
    assert "a sharp take" in captured["prompt"]


# --- batch-with-per-post-fallback pattern (as strategist_node orchestrates) ---


async def test_batch_then_fallback_pattern_fills_every_post():
    """Mirrors backend.pipeline.nodes.strategist_node's _draft_batch closure:
    batch call first, then a per-post fallback call for anything missing."""
    batch_fn = _fn_returning(json.dumps([{"post_id": "p1", "draft": "batched p1"}]))
    single_fn = _fn_returning("fallback draft")

    draft_map = await run_strategist_batch(ITEMS, "model-x", {}, acompletion_fn=batch_fn)
    for item in ITEMS:
        if item["post_id"] not in draft_map or not draft_map[item["post_id"]].strip():
            draft_map[item["post_id"]] = await run_strategist_single(
                item, "model-x", {}, acompletion_fn=single_fn
            )

    assert draft_map["p1"] == "batched p1"
    assert draft_map["p2"] == "fallback draft"
    assert draft_map["p3"] == "fallback draft"
