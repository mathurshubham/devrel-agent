"""Runner tests: start/poll/fetch, retry, and terminal-failure handling."""

import httpx
import pytest
import respx

from backend.ingestion import runner as runner_mod
from backend.ingestion.runner import (
    ApifyRunError,
    ApifyRunTimeout,
    ApifyRunner,
    actor_path,
    console_url_for,
)

ACTOR = "apimaestro/linkedin-posts-search-scraper-no-cookies"
RUN_ID = "run_abc123"
DATASET_ID = "ds_xyz789"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Collapse every poll interval and retry backoff to nothing."""

    async def instant(_seconds):
        return None

    monkeypatch.setattr(runner_mod.asyncio, "sleep", instant)


def _mock_apify(status_sequence, items, *, start_failures=0):
    """Register the three Apify endpoints with a scripted status sequence."""
    start_route = respx.post(
        f"https://api.apify.com/v2/acts/{actor_path(ACTOR)}/runs"
    )
    responses = [httpx.Response(500, text="apify is having a moment")] * start_failures
    responses.append(
        httpx.Response(201, json={"data": {"id": RUN_ID, "defaultDatasetId": DATASET_ID}})
    )
    start_route.mock(side_effect=responses)

    respx.get(f"https://api.apify.com/v2/actor-runs/{RUN_ID}").mock(
        side_effect=[httpx.Response(200, json={"data": {"status": s}}) for s in status_sequence]
    )
    respx.get(f"https://api.apify.com/v2/datasets/{DATASET_ID}/items").mock(
        return_value=httpx.Response(200, json=items)
    )
    return start_route


def test_actor_path_encodes_slash_as_tilde():
    assert actor_path("user/actor") == "user~actor"
    assert actor_path("simple-actor") == "simple-actor"


@respx.mock
async def test_run_actor_returns_dataset_items():
    items = [{"id": "1"}, {"id": "2"}]
    _mock_apify(["RUNNING", "SUCCEEDED"], items)

    result = await ApifyRunner("apify_api_test").run_actor(ACTOR, {"keyword": "evals"})

    assert result == items


@respx.mock
async def test_run_start_sends_input_as_json_body_and_token_as_query_param():
    start = _mock_apify(["SUCCEEDED"], [])
    await ApifyRunner("apify_api_secret").run_actor(ACTOR, {"keyword": "evals", "limit": 30})

    request = start.calls[0].request
    assert request.url.params["token"] == "apify_api_secret"
    assert b'"keyword"' in request.content


@respx.mock
async def test_run_start_is_retried_once_after_an_http_error():
    start = _mock_apify(["SUCCEEDED"], [{"id": "1"}], start_failures=1)

    result = await ApifyRunner("apify_api_test").run_actor(ACTOR, {})

    assert start.call_count == 2
    assert result == [{"id": "1"}]


@respx.mock
async def test_run_start_gives_up_after_the_single_retry():
    respx.post(f"https://api.apify.com/v2/acts/{actor_path(ACTOR)}/runs").mock(
        return_value=httpx.Response(500, text="still broken")
    )

    with pytest.raises(httpx.HTTPStatusError):
        await ApifyRunner("apify_api_test").run_actor(ACTOR, {})


@pytest.mark.parametrize("status", ["FAILED", "ABORTED", "TIMED-OUT"])
@respx.mock
async def test_terminal_failure_raises_with_the_console_url(status):
    _mock_apify(["RUNNING", status], [])

    with pytest.raises(ApifyRunError) as excinfo:
        await ApifyRunner("apify_api_test").run_actor(ACTOR, {})

    error = excinfo.value
    assert error.status == status
    assert error.run_id == RUN_ID
    assert error.console_url == console_url_for(RUN_ID)
    assert error.console_url in str(error)


@respx.mock
async def test_run_that_never_finishes_times_out_at_the_deadline():
    _mock_apify(["RUNNING"] * 10, [])

    with pytest.raises(ApifyRunTimeout) as excinfo:
        await ApifyRunner(
            "apify_api_test", timeout_seconds=15, poll_interval=5
        ).run_actor(ACTOR, {})

    assert console_url_for(RUN_ID) in str(excinfo.value)


@respx.mock
async def test_non_list_dataset_response_yields_no_items():
    _mock_apify(["SUCCEEDED"], {"error": "unexpected shape"})

    assert await ApifyRunner("apify_api_test").run_actor(ACTOR, {}) == []


async def test_runner_requires_a_token():
    with pytest.raises(ValueError):
        ApifyRunner("")
