"""Resolución de tenant por host (subdominio / dominio custom) con fallback de
cabecera `X-Tenant-Slug` (ADR-0012: el dominio *.replit.app no permite wildcard
por tenant; con dominios propios conectados se usa el host, como en el plan)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from shared.db import plain_session
from tenancy.models import Tenant

_ROOT_DOMAINS = ("autoken.es",)


def _slug_from_host(host: str) -> str | None:
    host = host.split(":")[0].lower()
    for root in _ROOT_DOMAINS:
        if host.endswith("." + root):
            sub = host.removesuffix("." + root)
            if sub and "." not in sub and sub not in ("www", "panel"):
                return sub
    return None


class TenantResolverMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.tenant = None
        host = request.headers.get("host", "")
        slug = _slug_from_host(host) or request.headers.get("X-Tenant-Slug")
        custom = None if slug else host.split(":")[0].lower()
        if slug or custom:
            async with plain_session() as session:
                stmt = select(Tenant).where(Tenant.status == "active")
                stmt = stmt.where(Tenant.slug == slug) if slug else stmt.where(
                    Tenant.custom_domain == custom
                )
                tenant = (await session.execute(stmt)).scalar_one_or_none()
                request.state.tenant = tenant
        return await call_next(request)
