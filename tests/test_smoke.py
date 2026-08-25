"""
M0 smoke tests: the app must import cleanly and expose the routers this
milestone rewired (auth, campaigns, inbox, org, prompts, safety, admin,
webhooks). This is the same check run by the M0 validation step:
`uv run python -c "from backend.main import app"`.
"""


def test_app_imports_and_exposes_expected_routes():
    from backend.main import app

    paths = {route.path for route in app.routes}

    assert "/health" in paths
    assert "/api/campaigns" in paths
    assert "/api/inbox/drafts" in paths
    assert "/api/inbox/drafts/{id}/lock" in paths
    assert "/api/inbox/drafts/{id}/confirm-posted" in paths
    assert "/api/org/llm-config" in paths
    assert "/api/org/kill-switch" in paths
    assert "/api/prompts" in paths
    assert "/api/safety" in paths
    assert "/api/admin/organizations" in paths
    assert "/api/webhooks/clerk" in paths

    # The TryEval export router was dropped from scope entirely.
    assert not any(p.startswith("/api/export") for p in paths)


def test_models_import_without_reddit_account():
    import backend.models as models

    assert not hasattr(models, "RedditAccount")
    assert hasattr(models, "OrgApifyToken")
    assert hasattr(models, "OrgMembership")


def test_celery_app_has_no_praw_publish_queue():
    from backend.celery_app import celery_app

    queue_names = {q.name for q in celery_app.conf.task_queues}
    assert queue_names == {"scraper", "langgen", "maintenance"}
