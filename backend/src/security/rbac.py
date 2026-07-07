"""Dependencias de autorización (BP-3: todo por Depends, nada de service locator)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, Request

from security.auth import decode_access_token
from shared.exceptions import ForbiddenError


@dataclass(frozen=True)
class Principal:
    subject_type: str          # 'user' | 'platform_admin'
    subject_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: str                  # 'user' | 'tenant_admin' | 'platform_admin'


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise ForbiddenError("Falta el token de acceso")
    return authorization.removeprefix("Bearer ").strip()


async def current_principal(
    request: Request, authorization: str | None = Header(default=None)
) -> Principal:
    payload = decode_access_token(_bearer(authorization))
    tenant_id = uuid.UUID(payload["tid"]) if payload.get("tid") else None
    principal = Principal(
        subject_type=payload["typ"],
        subject_id=uuid.UUID(payload["sub"]),
        tenant_id=tenant_id,
        role=payload["role"],
    )
    # Anti-cruce (§3.3): el tenant del token debe coincidir con el resuelto por host/cabecera.
    resolved = getattr(request.state, "tenant", None)
    if principal.subject_type == "user":
        if resolved is None or principal.tenant_id != resolved.id:
            raise ForbiddenError("El token no corresponde a esta asesoría")
    return principal


async def require_user(principal: Principal = Depends(current_principal)) -> Principal:
    if principal.subject_type != "user":
        raise ForbiddenError("Solo usuarios de asesoría")
    return principal


async def require_tenant_admin(principal: Principal = Depends(current_principal)) -> Principal:
    if principal.subject_type != "user" or principal.role != "tenant_admin":
        raise ForbiddenError("Requiere rol de administrador de la asesoría")
    return principal


async def require_platform_admin(principal: Principal = Depends(current_principal)) -> Principal:
    if principal.subject_type != "platform_admin":
        raise ForbiddenError("Requiere administrador de plataforma")
    return principal
