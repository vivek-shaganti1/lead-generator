"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import (
    auth,
    campaigns,
    crm,
    deliverability,
    discovery,
    intelligence,
    leads,
    metrics,
    public,
    stats,
    system,
)
from app.config import settings
from app.db import SessionLocal, init_db
from app.logging_config import get_logger
from app.security import ensure_admin_user, limiter
from app.services.pipeline import get_or_create_default_campaign

log = get_logger(__name__)


def bootstrap() -> None:
    """Create tables and seed the admin user + default campaign."""
    init_db()
    db = SessionLocal()
    try:
        ensure_admin_user(db)
        get_or_create_default_campaign(db)
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()
    log.info("app.started", env=settings.env, dry_run=settings.dry_run)
    if settings.env == "prod":
        if settings.secret_key.startswith("change-me"):
            log.error("app.insecure_secret_key")
        if settings.admin_password == "changeme123":
            log.error("app.default_admin_password")
    yield
    log.info("app.stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Lead Generator",
        description="Finds businesses with no working website and runs compliant "
                    "cold outreach offering to build one.",
        version=system.VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url=None,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    for router in (
        auth.router, discovery.router, leads.router, campaigns.router,
        stats.router, system.router, public.router, crm.router,
        intelligence.router, deliverability.router, metrics.router,
    ):
        app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root():
        return {"service": "lead-generator", "version": system.VERSION,
                "docs": "/docs", "health": "/health"}

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok", "service": "lead-generator", "version": system.VERSION}

    return app


app = create_app()
