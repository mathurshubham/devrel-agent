import os
from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from backend.limiter import limiter
from backend.utils.encryption import validate_primary_key
validate_primary_key()  # Trigger startup validation
from backend.api.org import router as org_router
from backend.api.webhooks import router as webhooks_router
from backend.api.export import router as export_router
from backend.api.safety import router as safety_router
from backend.api.campaigns import router as campaigns_router
from backend.api.inbox import router as inbox_router
from backend.api.prompts import router as prompts_router
from backend.api.admin import router as admin_router

app = FastAPI(
    title="Sentinel / TryEval OSS DevRel AI Agent",
    version="0.1.0"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Observability Toggle (TRD Section 7)
if os.getenv("ENABLE_METRICS", "false").lower() == "true":
    from starlette_exporter import PrometheusMiddleware, metrics
    app.add_middleware(PrometheusMiddleware)
    app.add_route("/metrics", metrics)

app.include_router(org_router)
app.include_router(webhooks_router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(export_router, prefix="/api")
app.include_router(safety_router)
app.include_router(campaigns_router)
app.include_router(inbox_router)
app.include_router(prompts_router)
app.include_router(admin_router, prefix="/api/admin", tags=["Super Admin"])

@app.get("/health")
@limiter.limit("60/minute")
async def health_check():
    """Basic health check and rate limit smoke test."""
    return {"status": "healthy", "timestamp": os.getpid()}
