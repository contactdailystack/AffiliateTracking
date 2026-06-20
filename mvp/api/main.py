from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
import os
import time
import logging
from sqlalchemy import text

from .routers.projects import router as projects_router
from .routers.scans import router as scans_router
from .routers.issues import router as issues_router
from .routers.integrations import router as integrations_router
from .routers.auth import router as auth_router
from .routers.payments import router as payments_router
from .db import SessionLocal
from .rate_limiter import redis_client
from ..common.upstash_rest import ping_upstash, get_rate_limit_client
from ..common.observability import configure_logging, record_request, render_metrics
from ..common.runtime import runtime

app = FastAPI(title=runtime.app_name)
STARTED_AT = time.time()
configure_logging(getattr(logging, runtime.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(scans_router)
app.include_router(issues_router)
app.include_router(integrations_router)
app.include_router(payments_router)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration = time.perf_counter() - start
        record_request(request.method, request.url.path, status_code, duration)
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            status_code,
            duration * 1000.0,
        )

# Serve frontend dashboard
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")


@app.get("/")
def root():
    """Serve the dashboard SPA."""
    index_path = os.path.join(_frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Affiliate Tracking Integrity Monitoring API", "docs": "/docs"}


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "service": runtime.app_name,
        "environment": runtime.app_env,
        "version": runtime.app_version,
        "uptime_seconds": int(time.time() - STARTED_AT),
    }


@app.get("/livez")
def livez():
    return {"status": "alive"}


@app.get("/readyz")
def readyz():
    try:
        session = SessionLocal()
        try:
            session.execute(text("SELECT 1"))
        finally:
            session.close()
        if get_rate_limit_client():
            if not ping_upstash():
                raise RuntimeError("Upstash ping failed")
        else:
            redis_client.ping()
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"not ready: {exc}")


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")


# Backward-compatible alias for health checks
@app.get("/health")
def health():
    return {"status": "ok"}

