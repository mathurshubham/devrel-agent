"""Unit tests for the Analyst pipeline's per-post nodes (triage/cluster/
stance/quotes) -- PRD V7 §5.6.

DB access inside these nodes is limited to org-scoped lookups
(get_org_llm_config/get_analyst_templates/_watchlist_block/get_org_settings)
-- all monkeypatched here so no real database is needed, matching the
"mocked LLM: happy, degradation, skip" brief in the M3 task.
"""

import pytest

from backend.pipeline import analyst_nodes
from backend.pipeline.analyst_schemas import ClusterResult, QuoteItem, QuotesResult, StanceResult, TriageResult

POSTS = [
    {
        "post_id": "p1",
        "platform": "LINKEDIN",
        "content": "We hit 0.89 faithfulness but customers still flag hallucinations.",
        "author_name": "Jane Doe",
        "author_headline": "Head of AI",
        "engagement_score": 42,
        "url": "https://linkedin.com/p1",
    },
    {
        "post_id": "p2",
        "platform": "LINKEDIN",
        "content": "Here's a generic AI hype post.",
        "author_name": "John Roe",
        "author_headline": "",
        "engagement_score": 3,
        "url": "https://linkedin.com/p2",
    },
]


class _FakeDB:
    def add(self, obj):
        pass

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def get(self, *a, **k):
        return None


class _FakeSessionCtx:
    async def __aenter__(self):
        return _FakeDB()

    async def __aexit__(self, *a):
        return False


def _session_local():
    return _FakeSessionCtx()


def _config():
    return {"configurable": {"session_local": _session_local, "redis_client": None}}


class _FakeLLMConfig:
    model_name = "openrouter/test-model"
    encrypted_api_key = None
    encrypted_with_key_version = 1
    custom_base_url = None


@pytest.fixture(autouse=True)
def _patch_common_lookups(monkeypatch):
    """Every node's first DB round-trip fetches llm_config + templates (+
    for triage, the watch-list block) -- stub these so tests only exercise
    the per-step LLM-call logic."""
    async def _fake_llm_config(db, org_id):
        return _FakeLLMConfig()

    async def _fake_templates(db, org_id):
        return {
            "master": "MASTER",
            "triage": "TRIAGE {POST_TEXT} {AUTHOR_NAME} {AUTHOR_TITLE}",
            "cluster": "CLUSTER {POST_TEXT}",
            "stance": "STANCE {POST_TEXT} {PILLAR_TAG}",
            "quotes": "QUOTES {POST_TEXT} {PILLAR_TAG} {STANCE_LABEL}",
            "brief": "BRIEF {WEEK_OF}",
        }

    async def _fake_org_settings(db, org_id):
        return None

    async def _fake_watchlist(db, org_id):
        return ""

    monkeypatch.setattr(analyst_nodes, "get_org_llm_config", _fake_llm_config)
    monkeypatch.setattr(analyst_nodes, "get_analyst_templates", _fake_templates)
    monkeypatch.setattr(analyst_nodes, "get_org_settings", _fake_org_settings)
    monkeypatch.setattr(analyst_nodes, "_watchlist_block", _fake_watchlist)


def _fake_response():
    return type("R", (), {})()


# ---------------------------------------------------------------------------
# triage_node
# ---------------------------------------------------------------------------


async def test_triage_node_happy_path(monkeypatch):
    async def _fake_structured(prompt, model, schema, call_kwargs, **kw):
        assert schema is TriageResult
        return (
            TriageResult(
                relevance_score=5, signal_score=5, buyer_persona="HEAD_OF_AI",
                watch_list_tier="TIER_1", decision="PROCESS_FULL", reason_short="on-topic",
            ),
            _fake_response(),
        )

    monkeypatch.setattr(analyst_nodes, "structured_completion", _fake_structured)

    state = {"posts": POSTS, "org_id": 1}
    result = await analyst_nodes.triage_node(state, _config())

    classifications = result["classifications"]
    assert len(classifications) == 2
    assert all(c["decision"] == "PROCESS_FULL" for c in classifications)
    assert classifications[0]["buyer_persona"] == "HEAD_OF_AI"
    assert classifications[0]["watch_list_tier"] == "TIER_1"


async def test_triage_node_degrades_to_process_light_on_llm_failure(monkeypatch):
    async def _fake_structured(*a, **kw):
        raise RuntimeError("LLM exploded")

    monkeypatch.setattr(analyst_nodes, "structured_completion", _fake_structured)

    state = {"posts": POSTS[:1], "org_id": 1}
    result = await analyst_nodes.triage_node(state, _config())

    c = result["classifications"][0]
    assert c["decision"] == "PROCESS_LIGHT"
    assert c["post_id"] == "p1"


async def test_triage_node_degrades_when_no_llm_configured(monkeypatch):
    async def _fake_no_llm_config(db, org_id):
        return None

    monkeypatch.setattr(analyst_nodes, "get_org_llm_config", _fake_no_llm_config)

    state = {"posts": POSTS[:1], "org_id": 1, "errors": []}
    result = await analyst_nodes.triage_node(state, _config())

    assert result["classifications"][0]["decision"] == "PROCESS_LIGHT"
    assert any("no LLM configured" in e for e in result["errors"])


async def test_triage_node_terminal_state_is_a_noop():
    result = await analyst_nodes.triage_node({"terminal": True}, _config())
    assert result == {}


# ---------------------------------------------------------------------------
# cluster_node
# ---------------------------------------------------------------------------


async def test_cluster_node_skips_skipped_posts(monkeypatch):
    calls = []

    async def _fake_structured(prompt, model, schema, call_kwargs, **kw):
        calls.append(prompt)
        return ClusterResult(primary_pillar="METRICS_ILLUSION", secondary_pillars=[]), _fake_response()

    monkeypatch.setattr(analyst_nodes, "structured_completion", _fake_structured)

    classifications = [
        analyst_nodes._base_classification(POSTS[0], decision="PROCESS_FULL"),
        analyst_nodes._base_classification(POSTS[1], decision="SKIP"),
    ]
    state = {"classifications": classifications, "posts": POSTS, "org_id": 1}
    result = await analyst_nodes.cluster_node(state, _config())

    assert len(calls) == 1  # only the non-SKIP post triggered an LLM call
    updated = {c["post_id"]: c for c in result["classifications"]}
    assert updated["p1"]["primary_pillar"] == "METRICS_ILLUSION"
    assert updated["p2"]["primary_pillar"] == "OTHER"  # untouched SKIP default


async def test_cluster_node_degrades_to_other_on_failure(monkeypatch):
    async def _fake_structured(*a, **kw):
        raise ValueError("bad json")

    monkeypatch.setattr(analyst_nodes, "structured_completion", _fake_structured)

    classifications = [analyst_nodes._base_classification(POSTS[0], decision="PROCESS_FULL")]
    state = {"classifications": classifications, "posts": POSTS, "org_id": 1}
    result = await analyst_nodes.cluster_node(state, _config())

    assert result["classifications"][0]["primary_pillar"] == "OTHER"
    assert result["classifications"][0]["secondary_pillars"] == []


# ---------------------------------------------------------------------------
# stance_node
# ---------------------------------------------------------------------------


async def test_stance_node_happy_path(monkeypatch):
    async def _fake_structured(prompt, model, schema, call_kwargs, **kw):
        return (
            StanceResult(stance="PROBLEM_PRESENT", confidence="HIGH", evidence_quote="quote here"),
            _fake_response(),
        )

    monkeypatch.setattr(analyst_nodes, "structured_completion", _fake_structured)

    classifications = [analyst_nodes._base_classification(POSTS[0], decision="PROCESS_FULL")]
    state = {"classifications": classifications, "posts": POSTS, "org_id": 1}
    result = await analyst_nodes.stance_node(state, _config())

    c = result["classifications"][0]
    assert c["stance"] == "PROBLEM_PRESENT"
    assert c["confidence"] == 0.9
    assert c["evidence_quote"] == "quote here"


async def test_stance_node_falls_back_to_neutral_on_invalid_stance(monkeypatch):
    async def _fake_structured(prompt, model, schema, call_kwargs, **kw):
        return StanceResult(stance="SOMETHING_ELSE", confidence="LOW"), _fake_response()

    monkeypatch.setattr(analyst_nodes, "structured_completion", _fake_structured)

    classifications = [analyst_nodes._base_classification(POSTS[0], decision="PROCESS_FULL")]
    state = {"classifications": classifications, "posts": POSTS, "org_id": 1}
    result = await analyst_nodes.stance_node(state, _config())

    assert result["classifications"][0]["stance"] == "NEUTRAL"


async def test_stance_node_degrades_on_failure_keeps_default(monkeypatch):
    async def _fake_structured(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(analyst_nodes, "structured_completion", _fake_structured)

    classifications = [analyst_nodes._base_classification(POSTS[0], decision="PROCESS_FULL")]
    state = {"classifications": classifications, "posts": POSTS, "org_id": 1}
    result = await analyst_nodes.stance_node(state, _config())

    # Default from _base_classification is untouched -- NEUTRAL / 0.5.
    c = result["classifications"][0]
    assert c["stance"] == "NEUTRAL"
    assert c["confidence"] == 0.5


# ---------------------------------------------------------------------------
# quotes_node
# ---------------------------------------------------------------------------


async def test_quotes_node_only_runs_for_process_full(monkeypatch):
    calls = []

    async def _fake_structured(prompt, model, schema, call_kwargs, **kw):
        calls.append(prompt)
        return QuotesResult(quotes=[QuoteItem(text="a real quote here", angle="ANGLE-1")]), _fake_response()

    monkeypatch.setattr(analyst_nodes, "structured_completion", _fake_structured)

    classifications = [
        analyst_nodes._base_classification(POSTS[0], decision="PROCESS_FULL"),
        analyst_nodes._base_classification(POSTS[1], decision="PROCESS_LIGHT"),
    ]
    state = {"classifications": classifications, "posts": POSTS, "org_id": 1}
    result = await analyst_nodes.quotes_node(state, _config())

    assert len(calls) == 1
    updated = {c["post_id"]: c for c in result["classifications"]}
    assert updated["p1"]["quotes"] == [{"text": "a real quote here", "angle": "ANGLE-1"}]
    assert updated["p2"]["quotes"] == []


async def test_quotes_node_degrades_to_empty_on_failure(monkeypatch):
    async def _fake_structured(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(analyst_nodes, "structured_completion", _fake_structured)

    classifications = [analyst_nodes._base_classification(POSTS[0], decision="PROCESS_FULL")]
    state = {"classifications": classifications, "posts": POSTS, "org_id": 1}
    result = await analyst_nodes.quotes_node(state, _config())

    assert result["classifications"][0]["quotes"] == []


async def test_quotes_node_no_process_full_is_a_noop_without_llm_config(monkeypatch):
    """If nothing is PROCESS_FULL, the node must not even fetch llm_config."""
    called = {"n": 0}

    async def _fake_llm_config(db, org_id):
        called["n"] += 1
        return _FakeLLMConfig()

    monkeypatch.setattr(analyst_nodes, "get_org_llm_config", _fake_llm_config)

    classifications = [analyst_nodes._base_classification(POSTS[0], decision="PROCESS_LIGHT")]
    state = {"classifications": classifications, "posts": POSTS, "org_id": 1}
    result = await analyst_nodes.quotes_node(state, _config())

    assert result["classifications"] == classifications
    assert called["n"] == 0
