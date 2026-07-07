"""Panel de plataforma (Julio + Alberto): login 2FA, alta de tenants en minutos,
branding, demo, métricas de consumo y ciclo de vida (Sprint 4, ARQ-3 sin BYPASSRLS)."""
from __future__ import annotations

import re
import uuid
from decimal import Decimal

import pyotp
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from companies.models import Company
from identity.models import PlatformAdmin, User
from invoice_intake.models import Invoice
from ocr.models import OcrExtraction
from security.audit import write_audit
from security.auth import create_access_token, hash_password, verify_password
from security.rate_limit import limit
from security.rbac import Principal, require_platform_admin
from shared.db import plain_session, tenant_session
from shared.exceptions import ConflictError, DomainError, ForbiddenError, NotFoundError
from tenancy.models import Tenant, TenantBranding

router = APIRouter(prefix="/platform", tags=["platform"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class PlatformLoginIn(BaseModel):
    email: EmailStr
    password: str
    otp: str = ""


class PlatformTokenOut(BaseModel):
    access_token: str
    totp_provisioning_uri: str | None = None


@router.post("/auth/login", response_model=PlatformTokenOut,
             dependencies=[Depends(limit("platform_login", 6, 60))])
async def platform_login(body: PlatformLoginIn) -> PlatformTokenOut:
    """2FA TOTP obligatorio: el primer login devuelve la URI de aprovisionamiento
    y no emite token hasta que se presenta un OTP válido."""
    async with plain_session() as session:
        admin = (
            await session.execute(select(PlatformAdmin).where(PlatformAdmin.email == body.email.lower()))
        ).scalar_one_or_none()
        if admin is None or not verify_password(body.password, admin.password_hash):
            raise ForbiddenError("Credenciales incorrectas")
        if admin.totp_secret is None:
            secret = pyotp.random_base32()
            admin.totp_secret = secret
            uri = pyotp.totp.TOTP(secret).provisioning_uri(
                name=admin.email, issuer_name="Autoken Plataforma"
            )
            return PlatformTokenOut(access_token="", totp_provisioning_uri=uri)
        if not body.otp or not pyotp.TOTP(admin.totp_secret).verify(body.otp, valid_window=1):
            raise ForbiddenError("Código 2FA incorrecto")
        await write_audit(session, tenant_id=None, actor_type="platform_admin",
                          actor_id=admin.id, action="login", entity="platform_admin",
                          entity_id=str(admin.id))
    return PlatformTokenOut(
        access_token=create_access_token("platform_admin", admin.id, None, "platform_admin")
    )


class TenantIn(BaseModel):
    slug: str
    name: str = Field(min_length=2, max_length=120)
    app_name: str = ""
    color_primary: str = "#FF7A00"
    color_secondary: str = "#1C1C1E"
    logo_url: str | None = None
    is_demo: bool = False
    admin_email: EmailStr
    admin_password: str = Field(min_length=12)


class TenantOut(BaseModel):
    id: str
    slug: str
    name: str
    status: str
    is_demo: bool
    custom_domain: str | None


@router.post("/tenants", response_model=TenantOut, status_code=201)
async def create_tenant(body: TenantIn, admin: Principal = Depends(require_platform_admin)) -> TenantOut:
    """Alta de asesoría en minutos (S4.1): tenant + branding + primer tenant_admin."""
    if not _SLUG_RE.match(body.slug):
        raise DomainError("Slug inválido: minúsculas, números y guiones (3-40 caracteres)")
    if not (_COLOR_RE.match(body.color_primary) and _COLOR_RE.match(body.color_secondary)):
        raise DomainError("Colores en formato #RRGGBB")
    async with plain_session() as session:
        dup = await session.execute(select(Tenant.id).where(Tenant.slug == body.slug))
        if dup.scalar_one_or_none() is not None:
            raise ConflictError("Ese slug ya está en uso")
        tenant = Tenant(slug=body.slug, name=body.name, is_demo=body.is_demo)
        session.add(tenant)
        await session.flush()
        session.add(
            TenantBranding(
                tenant_id=tenant.id,
                app_name=body.app_name or body.name,
                color_primary=body.color_primary,
                color_secondary=body.color_secondary,
                logo_url=body.logo_url,
            )
        )
        tenant_id = tenant.id
        await write_audit(session, tenant_id=tenant_id, actor_type="platform_admin",
                          actor_id=admin.subject_id, action="tenant_created", entity="tenant",
                          entity_id=str(tenant_id), payload={"slug": body.slug})
    async with tenant_session(tenant_id) as session:
        session.add(
            User(
                tenant_id=tenant_id,
                email=body.admin_email.lower(),
                full_name="Administración",
                password_hash=hash_password(body.admin_password),
                role="tenant_admin",
                status="active",
            )
        )
    return TenantOut(id=str(tenant_id), slug=body.slug, name=body.name,
                     status="active", is_demo=body.is_demo, custom_domain=None)


@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants(admin: Principal = Depends(require_platform_admin)) -> list[TenantOut]:
    async with plain_session() as session:
        rows = (await session.execute(select(Tenant).order_by(Tenant.created_at))).scalars().all()
    return [
        TenantOut(id=str(t.id), slug=t.slug, name=t.name, status=t.status,
                  is_demo=t.is_demo, custom_domain=t.custom_domain)
        for t in rows
    ]


class TenantMetrics(BaseModel):
    slug: str
    companies: int
    users: int
    invoices: int
    ocr_cost_eur: Decimal


@router.get("/tenants/{tenant_id}/metrics", response_model=TenantMetrics)
async def tenant_metrics(
    tenant_id: uuid.UUID, admin: Principal = Depends(require_platform_admin)
) -> TenantMetrics:
    """Acceso cross-tenant LEGÍTIMO (ARQ-3): sin BYPASSRLS — se fija el contexto
    del tenant explícitamente y ANTES se deja constancia en el audit_log."""
    async with plain_session() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("Asesoría no encontrada")
        await write_audit(session, tenant_id=tenant_id, actor_type="platform_admin",
                          actor_id=admin.subject_id, action="cross_tenant_read",
                          entity="tenant", entity_id=str(tenant_id),
                          payload={"scope": "metrics"})
    async with tenant_session(tenant_id) as session:
        companies = (await session.execute(select(func.count()).select_from(Company))).scalar_one()
        users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        invoices = (await session.execute(select(func.count()).select_from(Invoice))).scalar_one()
        cost = (
            await session.execute(select(func.coalesce(func.sum(OcrExtraction.cost), 0)))
        ).scalar_one()
    return TenantMetrics(slug=tenant.slug, companies=companies, users=users,
                         invoices=invoices, ocr_cost_eur=Decimal(cost))


class LifecycleIn(BaseModel):
    action: str  # 'suspend' | 'reactivate'


@router.post("/tenants/{tenant_id}/lifecycle", response_model=TenantOut)
async def tenant_lifecycle(
    tenant_id: uuid.UUID, body: LifecycleIn, admin: Principal = Depends(require_platform_admin)
) -> TenantOut:
    if body.action not in ("suspend", "reactivate"):
        raise DomainError("Acción no soportada")
    async with plain_session() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("Asesoría no encontrada")
        tenant.status = "suspended" if body.action == "suspend" else "active"
        await write_audit(session, tenant_id=tenant_id, actor_type="platform_admin",
                          actor_id=admin.subject_id, action=f"tenant_{body.action}",
                          entity="tenant", entity_id=str(tenant_id))
        return TenantOut(id=str(tenant.id), slug=tenant.slug, name=tenant.name,
                         status=tenant.status, is_demo=tenant.is_demo,
                         custom_domain=tenant.custom_domain)
