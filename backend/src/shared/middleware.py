"""Middlewares transversales.

SEC-2 (auditoría): el X-Correlation-ID entrante se valida contra un patrón
estricto antes de reflejarse (anti log-injection / response splitting).
SEC-6: cabeceras de seguridad servidas por la app (en Replit no hay proxy propio).
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_CID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Correlation-ID", "")
        cid = incoming if _CID_RE.match(incoming) else str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(correlation_id=cid)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("correlation_id")
        response.headers["X-Correlation-ID"] = cid
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )
        response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        response.headers.setdefault("Permissions-Policy", "camera=(self), geolocation=()")
        return response
