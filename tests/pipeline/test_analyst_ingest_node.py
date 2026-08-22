"""Unit tests for analyst_nodes.ingest_node -- the graph #2 entry node.

Real DB access here is limited to org/settings/token lookups and the
gather_analyst_posts() orchestration call, all monkeypatched so this stays
a pure unit test (the full ingest -> DB persistence path is covered against
real Postgres in tests/test_analyst_postgres_integration.py).
"""

from datetime import date

import pytest

from backend.pipeline import analyst_nodes


class _FakeOrg:
    id = 1
    is_active = True


class _FakeInactiveOrg:
    id = 1
    is_active = False


class _FakeAnalystRun:
    def __init__(self):
        self.status = "RUNNING"
        self.finished_at = None


class _FakeDB:
    def __init__(self, org=None, run=None):
        self._org = org
        self._run = run
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def get(self, model, pk):
        name = model.__name__
        if name == "Organization":
            return self._org
        if name == "AnalystRun":
            return self._run
        return None


class _FakeSessionCtx:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *a):
        return False


def _session_local_for(db):
    return lambda: _FakeSessionCtx(db)


def _config(db):
    return {"configurable": {"session_local": _session_local_for(db), "redis_client": None}}


@pytest.fixture(autouse=True)
def _patch_lookups(monkeypatch):
    async def _fake_org_settings(db, org_id):
        return None

    async def _fake_vault_tokens(db, org_id):
        return []

    monkeypatch.setattr(analyst_nodes, "get_org_settings", _fake_org_settings)
    monkeypatch.setattr(analyst_nodes, "get_active_apify_vault_tokens", _fake_vault_tokens)


async def test_ingest_node_terminal_when_org_missing():
    db = _FakeDB(org=None)
    state = {"org_id": 999, "run_id": 1, "week_of": "2026-08-17"}
    result = await analyst_nodes.ingest_node(state, _config(db))
    assert result == {"terminal": True, "terminal_reason": "org_missing"}


async def test_ingest_node_terminal_when_org_is_inactive():
    """Same guard scheduler_tick applies to reply-pipeline campaigns --
    a deactivated org must not get an Analyst run either."""
    db = _FakeDB(org=_FakeInactiveOrg())
    state = {"org_id": 1, "run_id": 1, "week_of": "2026-08-17"}
    result = await analyst_nodes.ingest_node(state, _config(db))
    assert result == {"terminal": True, "terminal_reason": "org_inactive"}


async def test_ingest_node_marks_run_complete_when_nothing_ingested(monkeypatch):
    async def _fake_gather(db, org_id, org_settings, tokens, *, redis_client=None):
        return [], [], []

    async def _fake_dedup(db, org_id, week_of):
        return set()

    monkeypatch.setattr(analyst_nodes, "gather_analyst_posts", _fake_gather)
    monkeypatch.setattr(analyst_nodes, "_previously_classified_post_ids", _fake_dedup)

    run = _FakeAnalystRun()
    db = _FakeDB(org=_FakeOrg(), run=run)
    state = {"org_id": 1, "run_id": 1, "week_of": "2026-08-17"}
    result = await analyst_nodes.ingest_node(state, _config(db))

    assert result["terminal"] is True
    assert result["terminal_reason"] == "no_posts"
    assert run.status == "COMPLETED"
    assert run.finished_at is not None


async def test_ingest_node_dedups_against_prior_weeks(monkeypatch):
    posts = [
        {"post_id": "p1", "platform": "LINKEDIN"},
        {"post_id": "p2", "platform": "LINKEDIN"},
    ]

    async def _fake_gather(db, org_id, org_settings, tokens, *, redis_client=None):
        return posts, [], []

    async def _fake_dedup(db, org_id, week_of):
        return {"p1"}  # already classified in an earlier week

    monkeypatch.setattr(analyst_nodes, "gather_analyst_posts", _fake_gather)
    monkeypatch.setattr(analyst_nodes, "_previously_classified_post_ids", _fake_dedup)

    db = _FakeDB(org=_FakeOrg())
    state = {"org_id": 1, "run_id": 1, "week_of": "2026-08-17"}
    result = await analyst_nodes.ingest_node(state, _config(db))

    assert [p["post_id"] for p in result["posts"]] == ["p2"]
    assert result.get("terminal") is not True


async def test_ingest_node_passes_through_competitor_posts_and_source_errors(monkeypatch):
    async def _fake_gather(db, org_id, org_settings, tokens, *, redis_client=None):
        return [{"post_id": "p1"}], [{"post_id": "c1", "competitor": "Acme"}], ["source X failed"]

    async def _fake_dedup(db, org_id, week_of):
        return set()

    monkeypatch.setattr(analyst_nodes, "gather_analyst_posts", _fake_gather)
    monkeypatch.setattr(analyst_nodes, "_previously_classified_post_ids", _fake_dedup)

    db = _FakeDB(org=_FakeOrg())
    state = {"org_id": 1, "run_id": 1, "week_of": "2026-08-17", "errors": []}
    result = await analyst_nodes.ingest_node(state, _config(db))

    assert result["competitor_posts"][0]["competitor"] == "Acme"
    assert "source X failed" in result["errors"]
