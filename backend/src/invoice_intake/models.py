"""Facturas y sus líneas. Snapshot OCR inmutable + veredicto de contraparte (§11.8, BD-5)."""
from __future__ import annotations

import datetime as dt
import decimal
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base
from shared.uuid7 import uuid7


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_invoices_id_tenant"),                # BD-1
        UniqueConstraint("tenant_id", "file_hash_sha256", name="uq_invoices_tenant_hash"),  # BD-3
        ForeignKeyConstraint(["company_id", "tenant_id"], ["companies.id", "companies.tenant_id"]),
        CheckConstraint("type IN ('received','issued')", name="ck_invoices_type"),
        CheckConstraint(
            "status IN ('processing','pending_review','confirmed','rejected')",
            name="ck_invoices_status",
        ),
        CheckConstraint("total IS NULL OR total >= 0", name="ck_invoices_total_nonneg"),   # BD-6
        CheckConstraint(
            "counterparty_cif_status IN ('valid','invalid','not_found','unverified')",
            name="ck_invoices_cp_status",
        ),
        CheckConstraint(
            "counterparty_name_match IN ('match','mismatch','unknown')",
            name="ck_invoices_cp_name",
        ),
        # Regla del plan §3.4: todo índice de negocio empieza por tenant_id.
        Index("ix_invoices_tenant_created", "tenant_id", "created_at"),
        Index("ix_invoices_tenant_company", "tenant_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(10))
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="processing")

    invoice_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    issue_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    # Snapshot inmutable de lo LEÍDO (BD-5); la identidad propia se INYECTA de companies.
    supplier_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supplier_cif: Mapped[str | None] = mapped_column(String(20), nullable=True)
    receiver_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    receiver_cif: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Veredicto del CIF de contraparte (§11.8 / ADR-0011).
    counterparty_cif_status: Mapped[str] = mapped_column(String(12), default="unverified")
    counterparty_name_match: Mapped[str] = mapped_column(String(10), default="unknown")
    counterparty_official_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    counterparty_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # BD-5

    file_key: Mapped[str] = mapped_column(String(300))
    file_mime: Mapped[str] = mapped_column(String(100))
    file_hash_sha256: Mapped[str] = mapped_column(String(64))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(                                        # BD-11
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvoiceTaxLine(Base):
    __tablename__ = "invoice_tax_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invoice_id", "tenant_id"], ["invoices.id", "invoices.tenant_id"], ondelete="CASCADE"
        ),
        CheckConstraint("base >= 0 AND cuota >= 0", name="ck_taxlines_nonneg"),
        Index("ix_taxlines_tenant_invoice", "tenant_id", "invoice_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)  # BD-8
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    iva_pct: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    base: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2))
    cuota: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2))


class InvoiceIrpf(Base):
    __tablename__ = "invoice_irpf"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invoice_id", "tenant_id"], ["invoices.id", "invoices.tenant_id"], ondelete="CASCADE"
        ),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # BD-8: 1:1
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    pct: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    cuota: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2))
