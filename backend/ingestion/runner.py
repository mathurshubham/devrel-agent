"""Generic Apify REST runner.

Async run/poll/fetch engine over the Apify v2 REST API. Ported from
``social-agent`` ``LinkedInIngestionService._run_actor_and_wait`` but made
platform-agnostic: the caller supplies the actor id and the input dict, and
gets back the raw dataset items.

Deliberately uses raw httpx instead of ``apify-client`` — the SDK's async
surface still performs blocking work internally and we run inside Celery
workers with a shared event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"

#: Seconds to wait before the single allowed retry of a failed run start.
RETRY_WAIT_SECONDS = 5
#: Seconds between run-status polls.
POLL_INTERVAL_SECONDS = 5
#: Hard deadline for a single actor run, in seconds.
RUN_TIMEOUT_SECONDS = 120

TERMINAL_FAILURE_STATUSES = ("FAILED", "ABORTED", "TIMED-OUT", "TIMED_OUT")


class ApifyRunError(RuntimeError):
    """An Apify actor run ended in a non-success terminal state.

    Carries the run console URL so operators can open the run directly from a
    log line or an error surfaced in the UI.
    """

    def __init__(self, run_id: str, status: str, actor_id: str = ""):
        self.run_id = run_id
        self.status = status
        self.actor_id = actor_id
        self.console_url = console_url_for(run_id)
        super().__init__(
            f"Apify actor run {run_id} ({actor_id or 'unknown actor'}) ended with "
            f"status {status}. Console: {self.console_url}"
        )


class ApifyRunTimeout(TimeoutError):
    """The run did not reach a terminal state within the deadline."""

    def __init__(self, run_id: str, timeout_seconds: int, actor_id: str = ""):
        self.run_id = run_id
        self.actor_id = actor_id
        self.console_url = console_url_for(run_id)
        super().__init__(
            f"Apify actor run {run_id} did not complete within {timeout_seconds}s. "
            f"Console: {self.console_url}"
        )


def console_url_for(run_id: str) -> str:
    return f"https://console.apify.com/actors/runs/{run_id}"


def actor_path(actor_id: str) -> str:
    """Apify REST requires ``/`` inside actor ids to be encoded as ``~``."""
    return actor_id.replace("/", "~")


class ApifyRunner:
    """Runs one Apify actor and returns its raw dataset items."""

    def __init__(
        self,
        token: str,
        *,
        timeout_seconds: int = RUN_TIMEOUT_SECONDS,
        poll_interval: int = POLL_INTERVAL_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        if not token:
            raise ValueError("ApifyRunner requires a token")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self._client = client

    # -- HTTP plumbing -------------------------------------------------

    async def _post_with_retry(
        self, client: httpx.AsyncClient, url: str, **kwargs: Any
    ) -> httpx.Response:
        """One attempt plus one retry after a fixed backoff."""
        try:
            resp = await client.post(url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500] if exc.response is not None else ""
            logger.warning(
                "Apify POST %s failed (%s) body=%s; retrying in %ds",
                url,
                exc.response.status_code if exc.response is not None else "?",
                body,
                RETRY_WAIT_SECONDS,
            )
        except httpx.RequestError as exc:
            logger.warning(
                "Apify POST %s transport error (%s); retrying in %ds",
                url,
                exc,
                RETRY_WAIT_SECONDS,
            )
        await asyncio.sleep(RETRY_WAIT_SECONDS)
        resp = await client.post(url, **kwargs)
        resp.raise_for_status()
        return resp

    # -- Public API ----------------------------------------------------

    async def run_actor(self, actor_id: str, actor_input: dict) -> list[dict]:
        """Start ``actor_id`` with ``actor_input``, wait for it, return items."""
        if self._client is not None:
            return await self._run(self._client, actor_id, actor_input)
        async with httpx.AsyncClient() as client:
            return await self._run(client, actor_id, actor_input)

    async def _run(
        self, client: httpx.AsyncClient, actor_id: str, actor_input: dict
    ) -> list[dict]:
        params = {"token": self.token}

        run_resp = await self._post_with_retry(
            client,
            f"{APIFY_BASE}/acts/{actor_path(actor_id)}/runs",
            params=params,
            json=actor_input,
            timeout=30,
        )
        run_data = run_resp.json()["data"]
        run_id = run_data["id"]
        dataset_id = run_data["defaultDatasetId"]
        logger.info(
            "Apify run started actor=%s run=%s console=%s",
            actor_id,
            run_id,
            console_url_for(run_id),
        )

        status = await self._poll_until_terminal(client, run_id, actor_id, params)
        if status != "SUCCEEDED":
            raise ApifyRunError(run_id, status, actor_id)

        items_resp = await client.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items",
            params={**params, "format": "json"},
            timeout=30,
        )
        items_resp.raise_for_status()
        items = items_resp.json()
        if not isinstance(items, list):
            logger.warning(
                "Apify dataset %s returned a %s, expected a list", dataset_id, type(items).__name__
            )
            return []
        logger.info("Apify run %s returned %d raw item(s)", run_id, len(items))
        return items

    async def _poll_until_terminal(
        self,
        client: httpx.AsyncClient,
        run_id: str,
        actor_id: str,
        params: dict,
    ) -> str:
        elapsed = 0
        status = "READY"
        while elapsed < self.timeout_seconds:
            await asyncio.sleep(self.poll_interval)
            elapsed += self.poll_interval
            status_resp = await client.get(
                f"{APIFY_BASE}/actor-runs/{run_id}", params=params, timeout=10
            )
            status_resp.raise_for_status()
            status = status_resp.json()["data"]["status"]
            if status == "SUCCEEDED":
                return status
            if status in TERMINAL_FAILURE_STATUSES:
                return status
        raise ApifyRunTimeout(run_id, self.timeout_seconds, actor_id)


async def run_actor(token: str, actor_id: str, actor_input: dict, **kwargs: Any) -> list[dict]:
    """Convenience wrapper for one-shot runs."""
    return await ApifyRunner(token, **kwargs).run_actor(actor_id, actor_input)
