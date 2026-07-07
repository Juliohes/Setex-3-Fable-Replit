"""Persistencia del pipeline OCR: extracciones, correcciones, supplier master y caché CIF."""
from __future__ import annotations

import datetime as dt
import decimal
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base
from shared.uuid7 import uuid7


class OcrExtraction(Base):
    __tablename__ = "ocr_extractions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invoice_id", "tenant_id"], ["invoices.id", "invoices.tenant_id"], ondelete="CASCADE"
        ),
        # ARQ-2: idempotencia — una fila por (factura, motor); el reintento no duplica coste.
        UniqueConstraint("invoice_id", "engine", name="uq_extraction_invoice_engine"),
        Index("ix_extractions_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    engine: Mapped[str] = mapped_column(String(40))
    raw_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    fields_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    field_confidences: Mapped[dict] = mapped_column(JSONB, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 5), default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OcrCorrection(Base):
    """Dataset de mejora continua: valor IA vs valor humano (capa 4 del pipeline)."""

    __tablename__ = "ocr_corrections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invoice_id", "tenant_id"], ["invoices.id", "invoices.tenant_id"], ondelete="CASCADE"
        ),
        Index("ix_corrections_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    field: Mapped[str] = mapped_column(String(60))
    ai_value: Mapped[str | None] = mapped_column(String(400), nullable=True)
    human_value: Mapped[str | None] = mapped_column(String(400), nullable=True)
    corrected_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Counterparty(Base):
    """Supplier master por tenant (L2 de la cadena del CIF, §11.8)."""

    __tablename__ = "counterparties"
    __table_args__ = (
        UniqueConstraint("tenant_id", "cif", name="uq_counterparties_tenant_cif"),
        UniqueConstraint("id", "tenant_id", name="uq_counterparties_id_tenant"),
        CheckConstraint(
            "name_source IN ('human','aeat','vies','borme','commercial')",
            name="ck_counterparties_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    cif: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    name_source: Mapped[str] = mapped_column(String(20), default="human")
    verified_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    times_seen: Mapped[int] = mapped_column(Integer, default=1)


class CifLookup(Base):
    """Caché GLOBAL de resoluciones externas (L4). Sin tenant_id a propósito.

    BD-2 (canal lateral documentado): esta tabla revela qué CIFs consultó la
    plataforma; por eso NUNCA se expone al tenant (ni `fetched_at`). Solo la
    usa el servicio de verificación. TTL diferenciado para "no existe" (BD-10).
    """

    __tablename__ = "cif_lookups"

    cif: Mapped[str] = mapped_column(String(20), primary_key=True)
    source: Mapped[str] = mapped_column(String(30), primary_key=True)
    exists: Mapped[bool] = mapped_column(Boolean)
    official_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=60 * 60 * 24 * 30)
