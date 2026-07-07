"""Application factory de Autoken Facturas v2 — modo Replit (ADR-0012).

Un solo proceso Reserved VM: API + worker OCR embebido (tarea asyncio) +
frontend estático. /docs solo fuera de producción (SEC-3).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from companies.router import router as companies_router
from identity.router import router as identity_router
from invoice_intake.router import router as invoices_router
from jobs.ocr_worker import handle_ocr_job
from jobs.queue import worker_loop
from platform_admin.health import router as health_router
from platform_admin.router import router as platform_router
from reporting.router import router as reporting_router
from shared.config import get_settings
from shared.db import engine
from shared.exceptions import DomainError
from shared.logging import configure_logging, get_logger
from shared.middleware import CorrelationIdMiddleware, SecurityHeadersMiddleware
from tenancy.middleware import TenantResolverMiddleware
from tenancy.router import router as tenancy_router

log = get_logger(__name__)
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    stop = asyncio.Event()
    worker_task: asyncio.Task | None = None
    if settings.auto_migrate:
        from shared.bootstrap import init_db

        await init_db(engine)
        log.info("db.bootstrap_done")
    worker_task = asyncio.create_task(worker_loop({"ocr": handle_ocr_job}, stop=stop))
    log.info("app.started", env=settings.app_env.value)
    yield
    stop.set()
    if worker_task:
        worker_task.cancel()
    await engine.dispose()
    log.info("app.stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",      # SEC-3
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.add_middleware(TenantResolverMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    prefix = settings.api_prefix
    app.include_router(health_router, prefix=prefix)
    app.include_router(tenancy_router, prefix=prefix)
    app.include_router(identity_router, prefix=prefix)
    app.include_router(companies_router, prefix=prefix)
    app.include_router(invoices_router, prefix=prefix)
    app.include_router(reporting_router, prefix=prefix)
    app.include_router(platform_router, prefix=prefix)

    if _FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            candidate = _FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(_FRONTEND_DIST / "index.html")

    return app


app = create_app()
