import os
from slowapi import Limiter
from slowapi.util import get_remote_address

# Teammate 4: Storage URI MUST match Redis URL for distributed rate limiting.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=REDIS_URL
)
