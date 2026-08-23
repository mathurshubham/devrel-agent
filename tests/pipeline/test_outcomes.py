from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from backend.pipeline.outcomes import OUTCOME_HOURS, fetch_reddit_comment_metrics

COMMENT_PERMALINK = "https://reddit.com/r/LLMDevs/comments/abc123/some_thread/def456/"

REDDIT_JSON_RESPONSE = [
    {"data": {"children": [{"data": {"id": "abc123", "title": "some thread"}}]}},
    {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "def456",
                        "score": 12,
                        "replies": {
                            "data": {
                                "children": [
                                    {"data": {"id": "reply1"}},
                                    {"data": {"id": "reply2"}},
                                ]
                            }
                        },
                    }
                }
            ]
        }
    },
]


@respx.mock
async def test_fetch_reddit_comment_metrics_happy_path():
    respx.get(COMMENT_PERMALINK.rstrip("/") + ".json").mock(
        return_value=httpx.Response(200, json=REDDIT_JSON_RESPONSE)
    )
    async with httpx.AsyncClient() as client:
        metrics = await fetch_reddit_comment_metrics(client, COMMENT_PERMALINK)

    assert metrics == {"reactions": 12, "replies": 2, "reposts": 0}


@respx.mock
async def test_fetch_reddit_comment_metrics_no_replies_yet():
    payload = [
        REDDIT_JSON_RESPONSE[0],
        {
            "data": {
                "children": [{"data": {"id": "def456", "score": 3, "replies": ""}}]
            }
        },
    ]
    respx.get(COMMENT_PERMALINK.rstrip("/") + ".json").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with httpx.AsyncClient() as client:
        metrics = await fetch_reddit_comment_metrics(client, COMMENT_PERMALINK)

    assert metrics == {"reactions": 3, "replies": 0, "reposts": 0}


@respx.mock
async def test_fetch_reddit_comment_metrics_returns_none_on_http_error():
    respx.get(COMMENT_PERMALINK.rstrip("/") + ".json").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        metrics = await fetch_reddit_comment_metrics(client, COMMENT_PERMALINK)

    assert metrics is None


@respx.mock
async def test_fetch_reddit_comment_metrics_returns_none_on_malformed_payload():
    respx.get(COMMENT_PERMALINK.rstrip("/") + ".json").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    async with httpx.AsyncClient() as client:
        metrics = await fetch_reddit_comment_metrics(client, COMMENT_PERMALINK)

    assert metrics is None


def test_outcome_hours_are_24_and_72():
    assert OUTCOME_HOURS == (24, 72)


# --- poll_engagement_outcomes orchestration (in-memory session stub) ---------


class _FakeScalarsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeExecResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalarsResult(self._rows)


class _FakeSession:
    """Just enough of AsyncSession for poll_engagement_outcomes's queries."""

    def __init__(self, drafts, existing_outcomes=None):
        self._drafts = drafts
        self._existing_outcomes = existing_outcomes or []
        self.added = []

    async def execute(self, stmt):
        # First call in the poller selects DraftReply rows; subsequent calls
        # (one per draft) select existing EngagementOutcome.hours_after.
        compiled = str(stmt)
        if "draft_replies" in compiled and "engagement_outcomes" not in compiled:
            return _FakeExecResult(self._drafts)
        return _FakeExecResult(self._existing_outcomes)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeDraft:
    def __init__(self, id, live_url, posted_at_source, platform):
        self.id = id
        self.live_url = live_url
        self.posted_at_source = posted_at_source
        self.platform = platform


@respx.mock
async def test_poll_engagement_outcomes_records_due_hours_for_reddit():
    from backend.models import PlatformEnum
    from backend.pipeline.outcomes import poll_engagement_outcomes

    respx.get(COMMENT_PERMALINK.rstrip("/") + ".json").mock(
        return_value=httpx.Response(200, json=REDDIT_JSON_RESPONSE)
    )

    posted_25h_ago = datetime.now(timezone.utc) - timedelta(hours=25)
    draft = _FakeDraft(id=1, live_url=COMMENT_PERMALINK, posted_at_source=posted_25h_ago, platform=PlatformEnum.REDDIT)
    fake_session = _FakeSession(drafts=[draft])

    def session_local():
        return fake_session

    stats = await poll_engagement_outcomes(session_local)

    assert stats["checked"] == 1
    assert stats["recorded"] == 1  # only the +24h mark is due at +25h
    assert len(fake_session.added) == 1
    outcome = fake_session.added[0]
    assert outcome.hours_after == 24
    assert outcome.reactions == 12
    assert outcome.replies == 2
    assert outcome.got_response is True


async def test_poll_engagement_outcomes_skips_non_reddit_platforms():
    from backend.models import PlatformEnum
    from backend.pipeline.outcomes import poll_engagement_outcomes

    posted_25h_ago = datetime.now(timezone.utc) - timedelta(hours=25)
    draft = _FakeDraft(id=2, live_url="https://linkedin.com/feed/update/urn/", posted_at_source=posted_25h_ago, platform=PlatformEnum.LINKEDIN)
    fake_session = _FakeSession(drafts=[draft])

    stats = await poll_engagement_outcomes(lambda: fake_session)

    assert stats["skipped_platform"] == 1
    assert fake_session.added == []


async def test_poll_engagement_outcomes_skips_drafts_not_yet_due():
    from backend.models import PlatformEnum
    from backend.pipeline.outcomes import poll_engagement_outcomes

    posted_1h_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    draft = _FakeDraft(id=3, live_url=COMMENT_PERMALINK, posted_at_source=posted_1h_ago, platform=PlatformEnum.REDDIT)
    fake_session = _FakeSession(drafts=[draft])

    stats = await poll_engagement_outcomes(lambda: fake_session)

    assert stats["checked"] == 0
    assert fake_session.added == []
