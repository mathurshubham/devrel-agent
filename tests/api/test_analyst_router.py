"""Router-level tests for /api/analyst -- dependency-override style
(tests/ingestion/test_router.py's pattern), not hitting a real DB or Celery
broker.
"""
from unittest.mock import MagicMock

from backend.models import AnalystRun, Competitor, IntelBrief, TargetAuthor
from backend.pipeline.analyst_graph import current_week_of


async def test_trigger_run_dispatches_and_returns_202(client, fake_db, monkeypatch):
    sent = {}

    def _fake_send_task(name, args):
        sent["name"] = name
        sent["args"] = args

    monkeypatch.setattr("backend.api.analyst.celery_app.send_task", _fake_send_task)

    async with client as ac:
        resp = await ac.post("/api/analyst/run")

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "RUNNING"
    assert body["run_id"] is not None
    assert sent["name"] == "backend.tasks.workers.analyst_task"
    assert sent["args"][0] == 1  # org_id
    assert sent["args"][1] == body["run_id"]


async def test_trigger_run_409_when_already_in_flight(client, fake_db):
    existing = AnalystRun(id=5, org_id=1, week_of=current_week_of(), status="RUNNING")
    fake_db.queue_execute_result(scalar_one_or_none=existing)

    async with client as ac:
        resp = await ac.post("/api/analyst/run")

    assert resp.status_code == 409


async def test_status_idle_when_no_runs_yet(client):
    async with client as ac:
        resp = await ac.get("/api/analyst/status")

    assert resp.status_code == 200
    assert resp.json() == {"run_id": None, "status": "IDLE", "week_of": None, "started_at": None, "finished_at": None}


async def test_status_returns_most_recent_run(client, fake_db):
    run = AnalystRun(id=3, org_id=1, week_of=current_week_of(), status="COMPLETED")
    fake_db.queue_execute_result(scalar_one_or_none=run)

    async with client as ac:
        resp = await ac.get("/api/analyst/status")

    assert resp.json()["run_id"] == 3
    assert resp.json()["status"] == "COMPLETED"


async def test_list_briefs_empty(client):
    async with client as ac:
        resp = await ac.get("/api/analyst/briefs")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_briefs_returns_summaries_newest_first(client, fake_db):
    briefs = [
        IntelBrief(id=2, org_id=1, week_of=current_week_of(), content_md="latest"),
        IntelBrief(id=1, org_id=1, week_of=current_week_of(), content_md="older"),
    ]
    fake_db.queue_execute_result(scalars_all=briefs)

    async with client as ac:
        resp = await ac.get("/api/analyst/briefs")

    body = resp.json()
    assert [b["id"] for b in body] == [2, 1]
    assert "content_md" not in body[0]  # summary, not detail


async def test_latest_brief_404_when_none(client):
    async with client as ac:
        resp = await ac.get("/api/analyst/briefs/latest")
    assert resp.status_code == 404


async def test_latest_brief_returns_full_content(client, fake_db):
    brief = IntelBrief(id=1, org_id=1, week_of=current_week_of(), content_md="# Brief")
    fake_db.queue_execute_result(scalar_one_or_none=brief)

    async with client as ac:
        resp = await ac.get("/api/analyst/briefs/latest")

    assert resp.json()["content_md"] == "# Brief"


async def test_get_brief_404_for_missing_id(client):
    async with client as ac:
        resp = await ac.get("/api/analyst/briefs/999")
    assert resp.status_code == 404


async def test_get_brief_404_when_belongs_to_another_org(client, fake_db):
    other_org_brief = IntelBrief(id=1, org_id=2, week_of=current_week_of(), content_md="not yours")
    fake_db.added.append(other_org_brief)

    async with client as ac:
        resp = await ac.get("/api/analyst/briefs/1")

    assert resp.status_code == 404


async def test_get_brief_returns_org_owned_brief(client, fake_db):
    brief = IntelBrief(id=1, org_id=1, week_of=current_week_of(), content_md="mine")
    fake_db.added.append(brief)

    async with client as ac:
        resp = await ac.get("/api/analyst/briefs/1")

    assert resp.json()["content_md"] == "mine"


async def test_forecast_empty_history_returns_stable_shape(client):
    async with client as ac:
        resp = await ac.get("/api/analyst/forecast")

    body = resp.json()
    assert body["trending"] == []
    assert body["declining"] == []
    assert body["stable"] == []
    assert body["recommended_focus"] == []


async def test_list_authors_empty(client):
    async with client as ac:
        resp = await ac.get("/api/analyst/authors")
    assert resp.json() == []


async def test_create_author_round_trips(client):
    async with client as ac:
        resp = await ac.post(
            "/api/analyst/authors", json={"name": "Jane Doe", "tier": 1, "profile_url": "https://x.com/jane"}
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Jane Doe"
    assert body["org_id"] == 1
    assert isinstance(body["id"], int)


async def test_delete_author_404_when_missing(client):
    async with client as ac:
        resp = await ac.delete("/api/analyst/authors/999")
    assert resp.status_code == 404


async def test_delete_author_404_when_wrong_org(client, fake_db):
    other_org_author = TargetAuthor(id=1, org_id=2, name="Not Yours")
    fake_db.added.append(other_org_author)

    async with client as ac:
        resp = await ac.delete("/api/analyst/authors/1")

    assert resp.status_code == 404


async def test_delete_author_succeeds_for_own_org(client, fake_db):
    author = TargetAuthor(id=1, org_id=1, name="Mine")
    fake_db.added.append(author)

    async with client as ac:
        resp = await ac.delete("/api/analyst/authors/1")

    assert resp.status_code == 204
    assert author in fake_db.deleted


async def test_list_competitors_empty(client):
    async with client as ac:
        resp = await ac.get("/api/analyst/competitors")
    assert resp.json() == []


async def test_create_competitor_round_trips(client):
    async with client as ac:
        resp = await ac.post(
            "/api/analyst/competitors",
            json={"name": "Acme", "platform": "LINKEDIN", "url": "https://linkedin.com/company/acme"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Acme"
    assert body["org_id"] == 1


async def test_delete_competitor_404_when_wrong_org(client, fake_db):
    other = Competitor(id=1, org_id=2, name="Not Yours")
    fake_db.added.append(other)

    async with client as ac:
        resp = await ac.delete("/api/analyst/competitors/1")

    assert resp.status_code == 404
