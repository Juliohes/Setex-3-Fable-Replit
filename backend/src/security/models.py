"""Audit log append-only con cadena de hashes (BD-7) y cola de jobs Postgres."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base
from shared.uuid7 import uuid7


class AuditLog(Base):
    """Append-only. `chain_hash = SHA256(payload_hash ‖ prev_hash)` por tenant:
    borrar o alterar una fila rompe la cadena y se detecta (tamper-evidence).
    La app no tiene rutas de UPDATE/DELETE sobre esta tabla."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_tenant_seq", "tenant_id", "seq"),
        CheckConstraint("actor_type IN ('user','tenant_admin','platform_admin','system')",
                        name="ck_audit_actor"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64), default="0" * 64)
    chain_hash: Mapped[str] = mapped_column(String(64))
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    """Cola de trabajos sobre Postgres (FOR UPDATE SKIP LOCKED).

    Decisión ADR-0012 (modo Replit): sustituye a Redis+arq — menos piezas,
    misma semántica at-least-once, e idempotencia por clave única (ARQ-2).
    Tabla de infraestructura: sin RLS y JAMÁS expuesta por la API.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','done','failed')", name="ck_jobs_status"),
        Index("ix_jobs_status_runat", "status", "run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    kind: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
