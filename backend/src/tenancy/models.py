"""Plano de plataforma: tenants y branding (sin RLS: se resuelven ANTES del contexto)."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base
from shared.uuid7 import uuid7


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$'", name="ck_tenants_slug_format"),
        CheckConstraint("status IN ('active','suspended')", name="ck_tenants_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    custom_domain: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")
    features: Mapped[dict] = mapped_column(JSONB, default=dict)  # feature flags por tenant (§11.8)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantBranding(Base):
    __tablename__ = "tenant_branding"

    # BD-13: relación 1:1 ⇒ la PK ES el tenant_id.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    app_name: Mapped[str] = mapped_column(String(80), default="Autoken Facturas")
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    color_primary: Mapped[str] = mapped_column(String(9), default="#FF7A00")
    color_secondary: Mapped[str] = mapped_column(String(9), default="#1C1C1E")
    favicon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
