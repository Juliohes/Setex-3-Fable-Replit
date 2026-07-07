"""Usuarios de tenant, membresías y refresh tokens. platform_admins va aparte (ARQ-3)."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base
from shared.uuid7 import uuid7


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),   # BD-13
        UniqueConstraint("id", "tenant_id", name="uq_users_id_tenant"),          # BD-1 (padre de FK compuesta)
        CheckConstraint("role IN ('user','tenant_admin')", name="ck_users_role"),
        CheckConstraint("status IN ('pending','active','disabled')", name="ck_users_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(160), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformAdmin(Base):
    """Plano de plataforma separado: evita BYPASSRLS y cuentas cruzadas (ARQ-3)."""

    __tablename__ = "platform_admins"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 2FA obligatorio al alta
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        # BD-1: FKs compuestas con tenant_id — imposible cruzar tenants ni con bug de app.
        ForeignKeyConstraint(["user_id", "tenant_id"], ["users.id", "users.tenant_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["company_id", "tenant_id"], ["companies.id", "companies.tenant_id"], ondelete="CASCADE"
        ),
    )

    # BD-8: PK natural explícita (nada de duplicados silenciosos).
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)


class RefreshToken(Base):
    """Refresh con rotación + detección de reuso (familia revocada en cascada)."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint("subject_type IN ('user','platform_admin')", name="ck_rt_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    subject_type: Mapped[str] = mapped_column(String(20))
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, default=uuid7)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotations: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
