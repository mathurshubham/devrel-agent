import redis.asyncio as redis
import time
import asyncio
import random
import httpx
from typing import Callable, Any
from backend.utils.encryption import decrypt

LOCK_KEY = "praw:token_refresh_lock:{account_id}"
TOKEN_KEY = "praw:access_token:{account_id}"
LOCK_TTL = 5000  # 5 second lock timeout (ms)
TOKEN_TTL = 55 * 60  # 55 minutes (seconds)

async def refresh_praw_token(reddit_account: Any) -> str:
    """
    Real OAuth refresh flow with Reddit.
    Requires reddit_account to have client_id, encrypted_secret, and refresh_token.
    """
    client_id = reddit_account.client_id
    client_secret = decrypt(reddit_account.encrypted_secret)
    refresh_token = decrypt(reddit_account.encrypted_refresh_token) if hasattr(reddit_account, 'encrypted_refresh_token') else None
    
    if not refresh_token:
        # Fallback if refresh_token is not available yet (scaffolding state)
        # In production, this should always be present for active accounts.
        return f"mock_token_{time.time()}"

    auth = httpx.BasicAuth(client_id, client_secret)
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    headers = {"User-Agent": "SentinelDevRelAgent/1.0"}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=auth,
            data=data,
            headers=headers
        )
        response.raise_for_status()
        result = response.json()
        return result["access_token"]

async def get_praw_token(
    account_id: int, 
    reddit_account: Any, 
    redis_client: redis.Redis,
) -> str:
    """
    Fetches a PRAW access token for the given account.
    Uses a Redis-based async distributed lock.
    """
    token_key = TOKEN_KEY.format(account_id=account_id)
    cached = await redis_client.get(token_key)
    if cached:
        return cached.decode()

    lock_key = LOCK_KEY.format(account_id=account_id)
    # nx=True: set if not exists, px=LOCK_TTL: expire in ms
    lock_acquired = await redis_client.set(lock_key, "1", nx=True, px=LOCK_TTL)

    if lock_acquired:
        try:
            # Refresh the token
            new_token = await refresh_praw_token(reddit_account)
            await redis_client.setex(token_key, TOKEN_TTL, new_token)
            return new_token
        finally:
            await redis_client.delete(lock_key)
    else:
        # Polling with jitter (TRD 4.6 requirement)
        for _ in range(20):
            await asyncio.sleep(0.1 + random.uniform(0, 0.05))
            cached = await redis_client.get(token_key)
            if cached:
                return cached.decode()
        
        raise RuntimeError(f"PRAW token refresh timed out for account {account_id}")

def _refresh_praw_token_mock(reddit_account: Any) -> str:
    """Mock refresh function for scaffolding/testing (sync)."""
    return f"mock_token_{time.time()}"
