"""Empresas cliente de cada asesoría."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base
from shared.uuid7 import uuid7


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "cif", name="uq_companies_tenant_cif"),  # BD-13
        UniqueConstraint("id", "tenant_id", name="uq_companies_id_tenant"),    # BD-1
        CheckConstraint("status IN ('pending','active','archived')", name="ck_companies_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    cif: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="active")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
