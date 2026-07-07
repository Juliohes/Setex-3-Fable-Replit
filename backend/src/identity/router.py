"""Autenticación y ciclo de vida de usuarios de tenant (S1.3, S1.4)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from companies.models import Company
from identity.models import Membership, User
from ocr.verification import validate_tax_id
from security.audit import write_audit
from security.auth import (
    create_access_token,
    hash_password,
    issue_refresh_token,
    rotate_refresh_token,
    verify_password,
)
from security.rate_limit import limit
from security.rbac import Principal, require_tenant_admin
from shared.db import plain_session, tenant_session
from shared.exceptions import ConflictError, DomainError, ForbiddenError, NotFoundError

router = APIRouter(tags=["identity"])


def _tenant_or_404(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise NotFoundError("Asesoría no encontrada")
    return tenant


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    role: str
    full_name: str
    company_ids: list[str]


@router.post("/auth/login", response_model=TokenOut, dependencies=[Depends(limit("login", 8, 60))])
async def login(request: Request, body: LoginIn) -> TokenOut:
    tenant = _tenant_or_404(request)
    async with tenant_session(tenant.id) as session:
        row = await session.execute(select(User).where(User.email == body.email.lower()))
        user = row.scalar_one_or_none()
        if user is None or not verify_password(body.password, user.password_hash):
            raise ForbiddenError("Email o contraseña incorrectos")
        if user.status != "active":
            raise ForbiddenError("Cuenta pendiente de aprobación por la asesoría")
        memberships = await session.execute(
            select(Membership.company_id).where(Membership.user_id == user.id)
        )
        company_ids = [str(c) for (c,) in memberships.all()]
    async with plain_session() as session:
        refresh = await issue_refresh_token(session, "user", user.id, tenant.id)
        await write_audit(
            session, tenant_id=tenant.id, actor_type=user.role, actor_id=user.id,
            action="login", entity="user", entity_id=str(user.id),
        )
    return TokenOut(
        access_token=create_access_token("user", user.id, tenant.id, user.role),
        refresh_token=refresh,
        role=user.role,
        full_name=user.full_name,
        company_ids=company_ids,
    )


class RefreshIn(BaseModel):
    refresh_token: str


@router.post("/auth/refresh", response_model=TokenOut)
async def refresh(request: Request, body: RefreshIn) -> TokenOut:
    tenant = _tenant_or_404(request)
    async with plain_session() as session:
        old, new_raw = await rotate_refresh_token(session, body.refresh_token)
    if old.tenant_id != tenant.id:
        raise ForbiddenError("El token no corresponde a esta asesoría")
    async with tenant_session(tenant.id) as session:
        user = (await session.execute(select(User).where(User.id == old.subject_id))).scalar_one_or_none()
        if user is None or user.status != "active":
            raise ForbiddenError("Cuenta no disponible")
        memberships = await session.execute(
            select(Membership.company_id).where(Membership.user_id == user.id)
        )
        company_ids = [str(c) for (c,) in memberships.all()]
    return TokenOut(
        access_token=create_access_token("user", user.id, tenant.id, user.role),
        refresh_token=new_raw,
        role=user.role,
        full_name=user.full_name,
        company_ids=company_ids,
    )


class RegisterIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=10, max_length=128)
    company_name: str = Field(min_length=2, max_length=200)
    company_cif: str


@router.post("/auth/register", status_code=201, dependencies=[Depends(limit("register", 5, 300))])
async def register(request: Request, body: RegisterIn) -> dict:
    """Registro con aprobación (S1.4): valida el CIF con dígito de control,
    crea usuario `pending` y, si la empresa no existe, empresa `pending`."""
    tenant = _tenant_or_404(request)
    cif_check = validate_tax_id(body.company_cif)
    if not cif_check.valid:
        raise DomainError(f"CIF de empresa inválido: {cif_check.reason}")
    clean_cif = "".join(body.company_cif.split()).upper()
    async with tenant_session(tenant.id) as session:
        exists = await session.execute(select(User.id).where(User.email == body.email.lower()))
        if exists.scalar_one_or_none() is not None:
            raise ConflictError("Ya existe un usuario con ese email en esta asesoría")
        company = (
            await session.execute(select(Company).where(Company.cif == clean_cif))
        ).scalar_one_or_none()
        if company is None:
            company = Company(tenant_id=tenant.id, name=body.company_name, cif=clean_cif, status="pending")
            session.add(company)
            await session.flush()
        user = User(
            tenant_id=tenant.id,
            email=body.email.lower(),
            full_name=body.full_name,
            password_hash=hash_password(body.password),
            role="user",
            status="pending",
        )
        session.add(user)
        await session.flush()
        session.add(Membership(user_id=user.id, company_id=company.id, tenant_id=tenant.id))
    async with plain_session() as session:
        await write_audit(
            session, tenant_id=tenant.id, actor_type="user", actor_id=user.id,
            action="register_requested", entity="user", entity_id=str(user.id),
            payload={"email": body.email.lower(), "company_cif": clean_cif},
        )
    return {"detail": "Registro recibido: pendiente de aprobación por tu asesoría"}


class PendingUserOut(BaseModel):
    id: str
    email: str
    full_name: str
    company_id: str | None


@router.get("/users/pending", response_model=list[PendingUserOut])
async def pending_users(
    request: Request, admin: Principal = Depends(require_tenant_admin)
) -> list[PendingUserOut]:
    tenant = _tenant_or_404(request)
    async with tenant_session(tenant.id) as session:
        rows = await session.execute(select(User).where(User.status == "pending"))
        users = rows.scalars().all()
        out = []
        for u in users:
            m = await session.execute(select(Membership.company_id).where(Membership.user_id == u.id))
            cid = m.scalar_one_or_none()
            out.append(
                PendingUserOut(id=str(u.id), email=u.email, full_name=u.full_name,
                               company_id=str(cid) if cid else None)
            )
    return out


@router.post("/users/{user_id}/approve")
async def approve_user(
    request: Request, user_id: uuid.UUID, admin: Principal = Depends(require_tenant_admin)
) -> dict:
    tenant = _tenant_or_404(request)
    async with tenant_session(tenant.id) as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            raise NotFoundError("Usuario no encontrado")
        user.status = "active"
    async with plain_session() as session:
        await write_audit(
            session, tenant_id=tenant.id, actor_type="tenant_admin", actor_id=admin.subject_id,
            action="user_approved", entity="user", entity_id=str(user_id),
        )
    return {"detail": "Usuario aprobado"}
