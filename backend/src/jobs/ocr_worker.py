"""Worker OCR: motores en paralelo → árbitro → validación determinista →
cadena de contraparte → persistencia (S2.3). NO es un God Object: cada paso
vive en su módulo; aquí solo se orquesta (PAT-7, pipeline funcional)."""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from companies.models import Company
from invoice_intake.models import Invoice
from invoice_intake.storage import build_storage
from ocr.arbiter import arbitrate
from ocr.counterparty.chain import build_resolvers, verify_counterparty_cif
from ocr.engines.base import build_engines
from ocr.models import OcrExtraction
from ocr.schema import ExtractionResult
from shared.config import get_settings
from shared.db import plain_session, tenant_session
from shared.events import OcrCompleted, bus
from shared.logging import get_logger
from tenancy.models import Tenant

log = get_logger(__name__)


async def handle_ocr_job(tenant_id: uuid.UUID, payload: dict) -> None:
    settings = get_settings()
    invoice_id = uuid.UUID(payload["invoice_id"])
    storage = build_storage(settings)

    async with tenant_session(tenant_id) as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        ).scalar_one_or_none()
        if invoice is None or invoice.status != "processing":
            return  # idempotencia: ya procesada o eliminada
        company = (
            await session.execute(select(Company).where(Company.id == invoice.company_id))
        ).scalar_one()
        own_cif, company_id = company.cif, company.id
        file_key, mime, inv_type = invoice.file_key, invoice.file_mime, invoice.type

    content = await storage.load(file_key)

    engines = build_engines(settings)
    results: list[ExtractionResult] = await asyncio.gather(
        *(engine.extract(content, mime) for engine in engines)
    ) if engines else []

    decision = arbitrate(results)
    f = decision.fields

    async with plain_session() as infra:
        tenant = (await infra.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
        features = tenant.features or {}
    resolvers = build_resolvers(settings, features)

    async with tenant_session(tenant_id) as session, plain_session() as infra:
        outcome = await verify_counterparty_cif(
            session, infra, f.counterparty_cif, f.counterparty_name, resolvers
        )

    async with tenant_session(tenant_id) as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        ).scalar_one()
        for r in results:
            session.add(
                OcrExtraction(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    invoice_id=invoice_id,
                    engine=r.engine,
                    raw_json=r.raw,
                    fields_json=r.fields.model_dump(mode="json"),
                    field_confidences=r.confidences,
                    duration_ms=r.duration_ms,
                    cost=r.cost_eur,
                )
            )
        # Snapshot de lo leído (la identidad propia se inyecta, §11.8.1)
        invoice.invoice_number = f.invoice_number
        invoice.issue_date = f.issue_date
        invoice.total = f.total
        if inv_type == "received":
            invoice.supplier_name = f.counterparty_name
            invoice.supplier_cif = f.counterparty_cif
            invoice.receiver_name, invoice.receiver_cif = None, own_cif
        else:
            invoice.receiver_name = f.counterparty_name
            invoice.receiver_cif = f.counterparty_cif
            invoice.supplier_name, invoice.supplier_cif = None, own_cif
        invoice.counterparty_cif_status = outcome.status.value
        invoice.counterparty_name_match = outcome.name_match.value
        invoice.counterparty_official_name = outcome.official_name
        invoice.counterparty_source = outcome.source
        invoice.status = "pending_review"

    await bus.publish(OcrCompleted(invoice_id=str(invoice_id), tenant_id=str(tenant_id)))
    log.info("ocr.completed", invoice_id=str(invoice_id), engines=[r.engine for r in results])
