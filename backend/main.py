import os
from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from backend.limiter import limiter
from backend.utils.encryption import _fernet  # Trigger startup validation
from backend.api.org import router as org_router
from backend.api.webhooks import router as webhooks_router
from backend.api.export import router as export_router

app = FastAPI(
    title="Sentinel / TryEval OSS DevRel AI Agent",
    version="0.1.0"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(org_router)
app.include_router(webhooks_router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(export_router, prefix="/api")

@app.get("/health")
@limiter.limit("60/minute")
async def health_check():
    """Basic health check and rate limit smoke test."""
    return {"status": "healthy", "timestamp": os.getpid()}
