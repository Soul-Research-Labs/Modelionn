"""FastAPI application — Modelionn Registry."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text as sa_text

from registry.core.config import settings
from registry.core.deps import engine
from registry.core.logging import setup_logging
from registry.core.sentry import init_sentry
from registry.models.database import Base

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    # Configure structured logging
    setup_logging(json_output=not settings.debug, level="DEBUG" if settings.debug else "INFO")
    # Optional Sentry error tracking
    init_sentry()
    # Startup: create tables if they don't exist (dev convenience)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # IPFS connectivity check
    try:
        from registry.storage.ipfs import IPFSStorage
        _ipfs = IPFSStorage()
        if not await _ipfs.exists("QmUNLLsPACCAfGEsRBiCAcKRoNk2EHmpPx1oUfHRbbsuEn"):
            logger.warning("IPFS health check: node reachable but empty directory CID not found")
        else:
            logger.info("IPFS health check passed")
    except Exception:
        logger.warning("IPFS unavailable at startup — uploads will fail until IPFS is reachable")
    logger.info("Modelionn registry started  network=%s  netuid=%d", settings.bt_network, settings.bt_netuid)
    yield
    # Graceful shutdown
    logger.info("Modelionn registry shutting down…")
    await engine.dispose()
    logger.info("Modelionn registry stopped")


app = FastAPI(
    title="Modelionn Registry",
    description="GPU-Accelerated ZK Prover Network on Bittensor",
    version="0.2.0",
    lifespan=lifespan,
)

# ── Error handlers ──────────────────────────────────────────
from registry.api.errors import register_error_handlers  # noqa: E402

register_error_handlers(app)

# ── Middleware (outermost → innermost) ──────────────────────
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from registry.api.middleware import (  # noqa: E402
    CSRFMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    TenantMiddleware,
)
from registry.api.middleware.metrics import MetricsMiddleware  # noqa: E402
from registry.api.middleware.api_key_auth import APIKeyAuthMiddleware  # noqa: E402
from registry.api.middleware.request_size import RequestSizeLimitMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Hotkey", "X-Nonce", "X-Signature", "X-Org-Slug", "X-Request-ID"],
)
app.add_middleware(MetricsMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_content_length=50 * 1024 * 1024)  # 50 MB
app.add_middleware(APIKeyAuthMiddleware)
app.add_middleware(TenantMiddleware)
app.add_middleware(SecurityHeadersMiddleware, enable_hsts=not settings.debug)
app.add_middleware(RequestIDMiddleware)

# ── Routes ──────────────────────────────────────────────────
from registry.api.routes.organizations import router as orgs_router  # noqa: E402
from registry.api.routes.audit import router as audit_router  # noqa: E402
from registry.api.routes.api_keys import router as api_keys_router  # noqa: E402
from registry.api.routes.circuits import router as circuits_router  # noqa: E402
from registry.api.routes.proofs import router as proofs_router  # noqa: E402
from registry.api.routes.provers import router as provers_router  # noqa: E402
from registry.api.routes.metrics import router as metrics_router  # noqa: E402
from registry.api.routes.webhooks import router as webhooks_router  # noqa: E402

app.include_router(orgs_router, prefix="/orgs", tags=["organizations"])
app.include_router(audit_router, prefix="/audit", tags=["audit"])
app.include_router(api_keys_router, prefix="/api-keys", tags=["api-keys"])
app.include_router(circuits_router, prefix="/circuits", tags=["circuits"])
app.include_router(proofs_router, prefix="/proofs", tags=["proofs"])
app.include_router(provers_router, prefix="/provers", tags=["provers"])
app.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
app.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "network": settings.bt_network}


@app.get("/health/ready")
async def readiness() -> dict[str, str | bool]:
    """Readiness probe — checks DB and Redis connectivity."""
    checks: dict[str, str | bool] = {"status": "ok"}

    # DB check
    try:
        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        checks["db"] = True
    except Exception:
        checks["db"] = False
        checks["status"] = "degraded"

    # Redis check (best-effort)
    try:
        from registry.core.cache import cache
        if cache._redis is not None:
            await cache._redis.ping()
            checks["redis"] = True
        else:
            checks["redis"] = False
    except Exception:
        checks["redis"] = False

    # IPFS check (best-effort)
    try:
        from registry.storage.ipfs import IPFSStorage
        _ipfs = IPFSStorage()
        checks["ipfs"] = await _ipfs.exists("QmUNLLsPACCAfGEsRBiCAcKRoNk2EHmpPx1oUfHRbbsuEn")
        if not checks["ipfs"]:
            checks["status"] = "degraded"
    except Exception:
        checks["ipfs"] = False
        checks["status"] = "degraded"

    if checks["status"] == "degraded":
        import fastapi
        raise fastapi.HTTPException(status_code=503, detail=checks)

    return checks
