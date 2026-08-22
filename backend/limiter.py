import os
from slowapi import Limiter
from slowapi.util import get_remote_address

# Teammate 4: Storage URI MUST match Redis URL for distributed rate limiting.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def rate_limit_key(request) -> str:
    """
    Key rate limits by the authenticated Clerk user id when available (set
    on request.state by backend/utils/auth.py's get_current_session), so
    users behind a shared/NATed IP don't share a limit and a single abusive
    user can't hide behind rotating addresses. Routes with no auth
    dependency (e.g. /health) fall back to remote address.
    """
    rate_key = getattr(request.state, "rate_key", None)
    if rate_key:
        return f"user:{rate_key}"
    return get_remote_address(request)


limiter = Limiter(
    key_func=rate_limit_key,
    storage_uri=REDIS_URL
)
