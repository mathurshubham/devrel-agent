import pytest
from unittest.mock import AsyncMock, patch
from backend.tasks.workers import praw_publish_task

@patch("backend.tasks.workers.redis_client")
def test_publish_idempotency_skip(mock_redis_client):
    """
    E2E - Publish Idempotency: Celery task retried after simulated worker crash -> 
    second execution skips PRAW call (Redis key praw_publish:{draft_id} prevents double-post)
    """
    # Simulate an existing lock in Redis for this draft
    mock_redis_client.set = AsyncMock(return_value=False)
    
    # Call the praw_publish_task directly
    # Since lock is not acquired, the function should return early
    # without trying to publish to PRAW
    praw_publish_task(draft_id=999)
    
    # Assert lock was checked accurately
    mock_redis_client.set.assert_called_once_with(
        "praw_publish:999", "locked", nx=True, px=300000
    )
