"""Acceso a datos y contexto de tenant.

ARQ-1 (auditoría, el "dragón nº1"): el contexto de tenant se fija con
`set_config(..., is_local => true)` — equivalente a SET LOCAL — dentro de una
transacción por petición. Al terminar la transacción el contexto desaparece,
por lo que una conexión devuelta al pool JAMÁS queda contaminada. Esto es
además la única forma correcta con Neon/Replit (PgBouncer en modo transacción).

PAT-6: este módulo es el punto ÚNICO donde se setea `app.tenant_id`.
ARQ-4: las políticas RLS son fail-closed (sin variable ⇒ 0 filas).
"""
from __future__ import annotations

import ssl
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from shared.config import get_settings


class Base(DeclarativeBase):
    pass


def _connect_args(url: str) -> dict:
    # Neon exige TLS; asyncpg no admite sslmode en la URL.
    if "neon.tech" in url or "sslmode=require" in url:
        ctx = ssl.create_default_context()
        return {"ssl": ctx}
    return {}


_settings = get_settings()
_clean_url = _settings.database_url.split("?")[0]
engine = create_async_engine(
    _clean_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    connect_args=_connect_args(_settings.database_url),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

_SET_CTX = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true), "
    "set_config('app.company_id', :company_id, true), "
    "set_config('app.company_scope', :company_scope, true)"
)


@asynccontextmanager
async def tenant_session(
    tenant_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
    company_scoped: bool = False,
) -> AsyncIterator[AsyncSession]:
    """Sesión con contexto RLS de tenant (y, opcionalmente, de empresa).

    `company_scoped=True` activa la política RESTRICTIVA de segundo nivel:
    el rol `user` solo ve filas de su empresa (`app.company_id`).
    """
    async with SessionLocal() as session:
        async with session.begin():
            await session.execute(
                _SET_CTX,
                {
                    "tenant_id": str(tenant_id),
                    "company_id": str(company_id) if company_id else "",
                    "company_scope": "1" if company_scoped else "",
                },
            )
            yield session


@asynccontextmanager
async def plain_session() -> AsyncIterator[AsyncSession]:
    """Sesión SIN contexto de tenant.

    Solo para tablas de plano de plataforma/infraestructura (tenants,
    tenant_branding, platform_admins, jobs, cif_lookups, audit_log).
    Las tablas de negocio con RLS FORCE devuelven 0 filas aquí (fail-closed).
    """
    async with SessionLocal() as session:
        async with session.begin():
            yield session
