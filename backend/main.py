import os
from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from backend.limiter import limiter
from backend.utils.encryption import _fernet  # Trigger startup validation
from backend.api.org import router as org_router

app = FastAPI(
    title="Sentinel / TryEval OSS DevRel AI Agent",
    version="0.1.0"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(org_router)

@app.get("/health")
@limiter.limit("60/minute")
async def health_check():
    """Basic health check and rate limit smoke test."""
    return {"status": "healthy", "timestamp": os.getpid()}
