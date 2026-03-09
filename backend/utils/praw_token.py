import redis
import time
import random
from typing import Callable

LOCK_KEY = "praw:token_refresh_lock:{account_id}"
TOKEN_KEY = "praw:access_token:{account_id}"
LOCK_TTL = 5000  # 5 second lock timeout (ms)
TOKEN_TTL = 55 * 60  # 55 minutes (seconds)

def get_praw_token(
    account_id: int, 
    reddit_account: any, 
    redis_client: redis.Redis,
    refresh_func: Callable[[any], str]
) -> str:
    """
    Fetches a PRAW access token for the given account.
    Uses a Redis-based distributed lock to ensure only one worker refreshes the token.
    Provides a polling fallback with jitter.
    """
    token_key = TOKEN_KEY.format(account_id=account_id)
    cached = redis_client.get(token_key)
    if cached:
        return cached.decode()

    lock_key = LOCK_KEY.format(account_id=account_id)
    # nx=True: set if not exists, px=LOCK_TTL: expire in ms
    lock_acquired = redis_client.set(lock_key, "1", nx=True, px=LOCK_TTL)

    if lock_acquired:
        try:
            # Refresh the token using the provided function
            new_token = refresh_func(reddit_account)
            redis_client.setex(token_key, TOKEN_TTL, new_token)
            return new_token
        finally:
            redis_client.delete(lock_key)
    else:
        # Polling with jitter (TRD 4.6 requirement)
        # Attempt to poll 20 times over ~2-3 seconds
        for _ in range(20):
            # Jitter: 0.1s base + 0 to 0.05s random
            time.sleep(0.1 + random.uniform(0, 0.05))
            cached = redis_client.get(token_key)
            if cached:
                return cached.decode()
        
        raise RuntimeError(f"PRAW token refresh timed out for account {account_id}")

def _refresh_praw_token_mock(reddit_account: any) -> str:
    """Mock refresh function for scaffolding/testing."""
    return f"mock_token_{time.time()}"
