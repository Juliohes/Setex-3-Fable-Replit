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
        raw_host = request.headers.get("host", "")
        host_only = raw_host.split(":")[0].lower()
        slug = _slug_from_host(raw_host) or request.headers.get("X-Tenant-Slug")
        async with plain_session() as session:
            tenant = None
            if slug:
                tenant = (
                    await session.execute(
                        select(Tenant).where(Tenant.status == "active", Tenant.slug == slug)
                    )
                ).scalar_one_or_none()
            # Fallback: dominio propio de la asesoría (p. ej. setex-fable.autoken.es o el
            # dominio de un cliente), cuando el subdominio no coincide con el slug interno.
            if tenant is None and host_only:
                tenant = (
                    await session.execute(
                        select(Tenant).where(
                            Tenant.status == "active", Tenant.custom_domain == host_only
                        )
                    )
                ).scalar_one_or_none()
            request.state.tenant = tenant
        return await call_next(request)
