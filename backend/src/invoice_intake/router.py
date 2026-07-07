"""Intake de facturas: subida segura, revisión, confirmación bloqueante e historial."""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from identity.models import Membership
from invoice_intake.models import Invoice, InvoiceIrpf, InvoiceTaxLine
from invoice_intake.storage import build_storage, make_file_key
from jobs.queue import enqueue
from ocr.counterparty.chain import upsert_supplier_master
from ocr.models import OcrCorrection, OcrExtraction
from ocr.verification import check_invoice_totals, check_tax_line, validate_tax_id
from security.audit import write_audit
from security.rbac import Principal, require_tenant_admin, require_user
from shared.config import get_settings
from shared.db import plain_session, tenant_session
from shared.exceptions import ConflictError, DomainError, ForbiddenError, NotFoundError
from shared.uuid7 import uuid7

router = APIRouter(prefix="/invoices", tags=["invoices"])

_ALLOWED_MIMES = {"application/pdf", "image/jpeg", "image/png"}
_MAGIC = {b"%PDF": "application/pdf", b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png"}


def _tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise NotFoundError("Asesoría no encontrada")
    return tenant


def _sniff_mime(content: bytes) -> str | None:
    """Validación de MIME REAL por magic bytes (control compensatorio de ClamAV
    en modo Replit, ADR-0012): jamás se confía en la extensión ni en la cabecera."""
    for magic, mime in _MAGIC.items():
        if content.startswith(magic):
            return mime
    return None


async def _user_company_id(session, principal: Principal, company_id: uuid.UUID | None) -> uuid.UUID:
    rows = await session.execute(select(Membership.company_id).where(Membership.user_id == principal.subject_id))
    companies = [c for (c,) in rows.all()]
    if not companies:
        raise ForbiddenError("Tu usuario no pertenece a ninguna empresa")
    if company_id is None:
        return companies[0]
    if company_id not in companies and principal.role != "tenant_admin":
        raise ForbiddenError("No perteneces a esa empresa")
    return company_id


class UploadOut(BaseModel):
    invoice_id: str
    status: str
    duplicate: bool = False


@router.post("/upload", response_model=UploadOut, status_code=201)
async def upload_invoice(
    request: Request,
    file: UploadFile,
    type: str,
    company_id: uuid.UUID | None = None,
    is_test: bool = False,
    principal: Principal = Depends(require_user),
) -> UploadOut:
    tenant = _tenant(request)
    settings = get_settings()
    if type not in ("received", "issued"):
        raise DomainError("El tipo debe ser 'received' o 'issued' (selector previo, regla 1)")
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise DomainError(f"Fichero demasiado grande (máx. {settings.max_upload_mb} MB)")
    mime = _sniff_mime(content)
    if mime is None or mime not in _ALLOWED_MIMES:
        raise DomainError("Formato no admitido: solo PDF, JPEG o PNG")
    file_hash = hashlib.sha256(content).hexdigest()
    is_test = is_test and principal.role == "tenant_admin"  # regla 3: solo admins marcan pruebas

    company_scoped = principal.role == "user"
    async with tenant_session(tenant.id) as session:
        cid = await _user_company_id(session, principal, company_id)
    async with tenant_session(tenant.id, cid, company_scoped=company_scoped) as session:
        dup = await session.execute(select(Invoice.id).where(Invoice.file_hash_sha256 == file_hash))
        if dup.scalar_one_or_none() is not None:
            raise ConflictError("Esta factura ya se subió antes (duplicado por huella del fichero)")
        invoice_id = uuid7()
        key = make_file_key(tenant.id, invoice_id, mime)
        storage = build_storage(settings)
        await storage.save(key, content, mime)
        session.add(
            Invoice(
                id=invoice_id,
                tenant_id=tenant.id,
                company_id=cid,
                uploaded_by=principal.subject_id,
                type=type,
                is_test=is_test,
                status="processing",
                file_key=key,
                file_mime=mime,
                file_hash_sha256=file_hash,
            )
        )
    # ARQ-2: clave de idempotencia derivada del hash ⇒ reintentos sin coste doble.
    await enqueue("ocr", f"ocr:{tenant.id}:{file_hash}", tenant.id, {"invoice_id": str(invoice_id)})
    async with plain_session() as session:
        await write_audit(session, tenant_id=tenant.id, actor_type=principal.role,
                          actor_id=principal.subject_id, action="invoice_uploaded",
                          entity="invoice", entity_id=str(invoice_id),
                          payload={"hash": file_hash, "type": type})
    return UploadOut(invoice_id=str(invoice_id), status="processing")


class TaxLineOut(BaseModel):
    iva_pct: Decimal | None
    base: Decimal | None
    cuota: Decimal | None


class ReviewOut(BaseModel):
    id: str
    status: str
    type: str
    # Los 3 campos SIEMPRE visibles (regla 12)
    total: Decimal | None
    counterparty_cif: str | None
    issue_date: dt.date | None
    # Veredicto del CIF de contraparte (§11.8)
    counterparty_cif_status: str
    counterparty_name_match: str
    counterparty_official_name: str | None
    counterparty_source: str | None
    counterparty_name: str | None
    # Identidad propia INYECTADA (no leída)
    own_name: str
    own_cif: str
    own_cif_as_read_ok: bool | None
    # Plegado
    invoice_number: str | None
    tax_lines: list[TaxLineOut]
    irpf_pct: Decimal | None
    irpf_cuota: Decimal | None
    field_flags: dict[str, str]
    confirm_blocked: bool
    confirm_blocked_reason: str | None


async def _load_review(session, tenant_id: uuid.UUID, invoice: Invoice) -> ReviewOut:
    from companies.models import Company

    company = (
        await session.execute(select(Company).where(Company.id == invoice.company_id))
    ).scalar_one()
    lines = (
        await session.execute(select(InvoiceTaxLine).where(InvoiceTaxLine.invoice_id == invoice.id))
    ).scalars().all()
    irpf = (
        await session.execute(select(InvoiceIrpf).where(InvoiceIrpf.invoice_id == invoice.id))
    ).scalar_one_or_none()
    extractions = (
        await session.execute(select(OcrExtraction).where(OcrExtraction.invoice_id == invoice.id))
    ).scalars().all()

    flags: dict[str, str] = {}
    own_read_ok: bool | None = None
    tax_lines: list[TaxLineOut] = [
        TaxLineOut(iva_pct=line.iva_pct, base=line.base, cuota=line.cuota) for line in lines
    ]
    irpf_pct = irpf.pct if irpf else None
    irpf_cuota = irpf.cuota if irpf else None
    if not lines and extractions:
        best = max(extractions, key=lambda e: len(e.field_confidences))
        fj = best.fields_json or {}
        for name in ("total", "counterparty_cif", "issue_date", "invoice_number"):
            conf = best.field_confidences.get(name)
            value = fj.get(name)
            flags[name] = "missing" if value is None else ("ok" if (conf or 0) >= 0.85 else "review")
        tax_lines = [
            TaxLineOut(
                iva_pct=Decimal(str(tl["iva_pct"])) if tl.get("iva_pct") is not None else None,
                base=Decimal(str(tl["base"])) if tl.get("base") is not None else None,
                cuota=Decimal(str(tl["cuota"])) if tl.get("cuota") is not None else None,
            )
            for tl in fj.get("tax_lines", [])
        ]
        if fj.get("irpf_pct") is not None:
            irpf_pct = Decimal(str(fj["irpf_pct"]))
        if fj.get("irpf_cuota") is not None:
            irpf_cuota = Decimal(str(fj["irpf_cuota"]))
        own_read = fj.get("own_cif_as_read")
        own_read_ok = None if own_read is None else (
            "".join(str(own_read).split()).upper() == company.cif
        )

    cp_cif = invoice.supplier_cif if invoice.type == "received" else invoice.receiver_cif
    cp_name = invoice.supplier_name if invoice.type == "received" else invoice.receiver_name

    blocked = False
    reason = None
    if invoice.counterparty_cif_status in ("invalid", "not_found"):
        blocked = True
        reason = (
            "CIF de la contraparte inválido" if invoice.counterparty_cif_status == "invalid"
            else "El CIF de la contraparte no consta en el censo"
        )
    elif own_read_ok is False:
        blocked = True
        reason = "El CIF propio leído no coincide con el de tu empresa: revisa la foto o el selector"

    return ReviewOut(
        id=str(invoice.id),
        status=invoice.status,
        type=invoice.type,
        total=invoice.total,
        counterparty_cif=cp_cif,
        issue_date=invoice.issue_date,
        counterparty_cif_status=invoice.counterparty_cif_status,
        counterparty_name_match=invoice.counterparty_name_match,
        counterparty_official_name=invoice.counterparty_official_name,
        counterparty_source=invoice.counterparty_source,
        counterparty_name=cp_name,
        own_name=company.name,
        own_cif=company.cif,
        own_cif_as_read_ok=own_read_ok,
        invoice_number=invoice.invoice_number,
        tax_lines=tax_lines,
        irpf_pct=irpf_pct,
        irpf_cuota=irpf_cuota,
        field_flags=flags,
        confirm_blocked=blocked,
        confirm_blocked_reason=reason,
    )


@router.get("/{invoice_id}", response_model=ReviewOut)
async def get_invoice(
    request: Request, invoice_id: uuid.UUID, principal: Principal = Depends(require_user)
) -> ReviewOut:
    tenant = _tenant(request)
    company_scoped = principal.role == "user"
    async with tenant_session(tenant.id) as s0:
        cid = await _user_company_id(s0, principal, None) if company_scoped else None
    async with tenant_session(tenant.id, cid, company_scoped=company_scoped) as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        ).scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Factura no encontrada")
        return await _load_review(session, tenant.id, invoice)


class TaxLineIn(BaseModel):
    iva_pct: Decimal
    base: Decimal
    cuota: Decimal


class ConfirmIn(BaseModel):
    responsibility_accepted: bool
    invoice_number: str | None = None
    issue_date: dt.date | None = None
    counterparty_name: str | None = None
    counterparty_cif: str | None = None
    total: Decimal | None = None
    tax_lines: list[TaxLineIn] = Field(default_factory=list)
    irpf_pct: Decimal | None = None
    irpf_cuota: Decimal | None = None


@router.post("/{invoice_id}/confirm", response_model=ReviewOut)
async def confirm_invoice(
    request: Request,
    invoice_id: uuid.UUID,
    body: ConfirmIn,
    principal: Principal = Depends(require_user),
) -> ReviewOut:
    """Confirmación humana (S2.4/S2.5). Reglas 7-8 y 11-12: checkbox obligatorio,
    bloqueo por veredicto del CIF y por descuadre aritmético grave."""
    tenant = _tenant(request)
    if not body.responsibility_accepted:
        raise DomainError("Debes marcar la casilla de responsabilidad para confirmar")
    cif_check = validate_tax_id(body.counterparty_cif)
    if not cif_check.valid:
        raise DomainError(f"No se puede confirmar: {cif_check.reason}")
    if body.total is None or not body.tax_lines:
        raise DomainError("No se puede confirmar sin total y al menos un tramo de IVA")
    totals_check = check_invoice_totals(
        [(ln.base, ln.iva_pct, ln.cuota) for ln in body.tax_lines], body.irpf_cuota, body.total
    )
    if not totals_check.valid:
        raise DomainError(f"No se puede confirmar: {totals_check.reason}")

    company_scoped = principal.role == "user"
    async with tenant_session(tenant.id) as s0:
        cid = await _user_company_id(s0, principal, None) if company_scoped else None
    async with tenant_session(tenant.id, cid, company_scoped=company_scoped) as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        ).scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Factura no encontrada")
        if invoice.status not in ("pending_review",):
            raise ConflictError("La factura no está pendiente de revisión")
        if invoice.counterparty_cif_status in ("invalid", "not_found"):
            raise DomainError("Confirmación bloqueada: el CIF de la contraparte es inválido o inexistente")

        clean_cif = "".join((body.counterparty_cif or "").split()).upper()
        # Capa 4 (mejora continua): toda edición humana ⇒ fila en ocr_corrections
        edited = {
            "invoice_number": (invoice.invoice_number, body.invoice_number),
            "issue_date": (invoice.issue_date, body.issue_date),
            "total": (invoice.total, body.total),
            "counterparty_cif": (
                invoice.supplier_cif if invoice.type == "received" else invoice.receiver_cif,
                clean_cif,
            ),
            "counterparty_name": (
                invoice.supplier_name if invoice.type == "received" else invoice.receiver_name,
                body.counterparty_name,
            ),
        }
        for field, (ai_value, human_value) in edited.items():
            if str(ai_value or "") != str(human_value or ""):
                session.add(
                    OcrCorrection(
                        tenant_id=tenant.id,
                        company_id=invoice.company_id,
                        invoice_id=invoice.id,
                        field=field,
                        ai_value=str(ai_value) if ai_value is not None else None,
                        human_value=str(human_value) if human_value is not None else None,
                        corrected_by=principal.subject_id,
                    )
                )

        invoice.invoice_number = body.invoice_number
        invoice.issue_date = body.issue_date
        invoice.total = body.total
        if invoice.type == "received":
            invoice.supplier_cif, invoice.supplier_name = clean_cif, body.counterparty_name
        else:
            invoice.receiver_cif, invoice.receiver_name = clean_cif, body.counterparty_name

        for old in (
            await session.execute(select(InvoiceTaxLine).where(InvoiceTaxLine.invoice_id == invoice.id))
        ).scalars():
            await session.delete(old)
        for line in body.tax_lines:
            session.add(
                InvoiceTaxLine(
                    tenant_id=tenant.id, company_id=invoice.company_id, invoice_id=invoice.id,
                    iva_pct=line.iva_pct, base=line.base, cuota=line.cuota,
                )
            )
        old_irpf = (
            await session.execute(select(InvoiceIrpf).where(InvoiceIrpf.invoice_id == invoice.id))
        ).scalar_one_or_none()
        if old_irpf is not None:
            await session.delete(old_irpf)
        if body.irpf_pct is not None and body.irpf_cuota is not None:
            session.add(
                InvoiceIrpf(invoice_id=invoice.id, tenant_id=tenant.id,
                            company_id=invoice.company_id, pct=body.irpf_pct, cuota=body.irpf_cuota)
            )

        invoice.status = "confirmed"
        invoice.confirmed_by = principal.subject_id
        invoice.confirmed_at = dt.datetime.now(dt.UTC)
        if body.counterparty_name:
            await upsert_supplier_master(session, tenant.id, clean_cif, body.counterparty_name)
        out = await _load_review(session, tenant.id, invoice)

    async with plain_session() as session:
        await write_audit(
            session, tenant_id=tenant.id, actor_type=principal.role, actor_id=principal.subject_id,
            action="invoice_confirmed", entity="invoice", entity_id=str(invoice_id),
            payload={"snapshot": body.model_dump(mode="json"), "responsibility_accepted": True},
        )
    return out


class TaxLinesEditIn(BaseModel):
    tax_lines: list[TaxLineIn] = Field(default_factory=list)


# Tipos de IVA fijos admitidos en España (§ desglose): 21, 10, 4 y 0.
_ALLOWED_IVA_PCT = (Decimal("21"), Decimal("10"), Decimal("4"), Decimal("0"))


def _tax_lines_summary(lines: list[tuple[Decimal, Decimal, Decimal]]) -> str:
    """Resumen compacto y estable de un desglose para la traza de correcciones."""
    parts = [f"{iva_pct}%: base {base} / cuota {cuota}" for iva_pct, base, cuota in lines]
    text = "; ".join(parts) if parts else "(sin tramos)"
    return text[:400]


@router.patch("/{invoice_id}/tax-lines", response_model=ReviewOut)
async def edit_tax_lines(
    request: Request,
    invoice_id: uuid.UUID,
    body: TaxLinesEditIn,
    principal: Principal = Depends(require_tenant_admin),
) -> ReviewOut:
    """Edición del desglose de IVA desde el panel del admin (no es la confirmación
    inicial: sin checkbox de responsabilidad, admite pending_review y confirmed).
    Reemplaza los tramos por completo, revalidando cada tramo y el cuadre global
    contra el IRPF ya guardado y el total de la factura."""
    tenant = _tenant(request)
    if not body.tax_lines:
        raise DomainError("El desglose debe tener al menos un tramo de IVA")
    for line in body.tax_lines:
        if line.iva_pct not in _ALLOWED_IVA_PCT:
            raise DomainError(
                f"Tipo de IVA no permitido: {line.iva_pct}. "
                "Solo se admiten 21%, 10%, 4% y 0%"
            )
        line_check = check_tax_line(line.base, line.iva_pct, line.cuota)
        if not line_check.valid:
            raise DomainError(f"Tramo de IVA {line.iva_pct}% inválido: {line_check.reason}")

    async with tenant_session(tenant.id) as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        ).scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Factura no encontrada")
        if invoice.total is None:
            raise DomainError("La factura no tiene total para cuadrar el desglose")

        irpf = (
            await session.execute(select(InvoiceIrpf).where(InvoiceIrpf.invoice_id == invoice.id))
        ).scalar_one_or_none()
        irpf_cuota = irpf.cuota if irpf else None

        totals_check = check_invoice_totals(
            [(ln.base, ln.iva_pct, ln.cuota) for ln in body.tax_lines], irpf_cuota, invoice.total
        )
        if not totals_check.valid:
            raise DomainError(f"El desglose no cuadra: {totals_check.reason}")

        old_lines = (
            await session.execute(select(InvoiceTaxLine).where(InvoiceTaxLine.invoice_id == invoice.id))
        ).scalars().all()
        ai_summary = _tax_lines_summary(
            [(ln.iva_pct, ln.base, ln.cuota) for ln in old_lines]
        )
        new_summary = _tax_lines_summary(
            [(ln.iva_pct, ln.base, ln.cuota) for ln in body.tax_lines]
        )
        for old in old_lines:
            await session.delete(old)
        for line in body.tax_lines:
            session.add(
                InvoiceTaxLine(
                    tenant_id=tenant.id, company_id=invoice.company_id, invoice_id=invoice.id,
                    iva_pct=line.iva_pct, base=line.base, cuota=line.cuota,
                )
            )
        # Capa 4 (mejora continua): la edición humana del desglose deja rastro.
        session.add(
            OcrCorrection(
                tenant_id=tenant.id,
                company_id=invoice.company_id,
                invoice_id=invoice.id,
                field="tax_lines",
                ai_value=ai_summary,
                human_value=new_summary,
                corrected_by=principal.subject_id,
            )
        )
        out = await _load_review(session, tenant.id, invoice)

    async with plain_session() as session:
        await write_audit(
            session, tenant_id=tenant.id, actor_type=principal.role, actor_id=principal.subject_id,
            action="invoice_desglose_edited", entity="invoice", entity_id=str(invoice_id),
            payload={"tax_lines": [
                {"iva_pct": str(ln.iva_pct), "base": str(ln.base), "cuota": str(ln.cuota)}
                for ln in body.tax_lines
            ]},
        )
    return out


class HistoryItem(BaseModel):
    id: str
    status: str
    type: str
    total: Decimal | None
    counterparty: str | None
    issue_date: dt.date | None
    created_at: dt.datetime


@router.get("", response_model=list[HistoryItem])
async def history(
    request: Request, days: int = 7, principal: Principal = Depends(require_user)
) -> list[HistoryItem]:
    """Historial del usuario (S2.6): últimos 7 días por defecto, como en la v1."""
    tenant = _tenant(request)
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=min(days, 31))
    company_scoped = principal.role == "user"
    async with tenant_session(tenant.id) as s0:
        cid = await _user_company_id(s0, principal, None) if company_scoped else None
    async with tenant_session(tenant.id, cid, company_scoped=company_scoped) as session:
        rows = (
            await session.execute(
                select(Invoice).where(Invoice.created_at >= since).order_by(Invoice.created_at.desc())
            )
        ).scalars().all()
    return [
        HistoryItem(
            id=str(i.id), status=i.status, type=i.type, total=i.total,
            counterparty=i.supplier_name if i.type == "received" else i.receiver_name,
            issue_date=i.issue_date, created_at=i.created_at,
        )
        for i in rows
    ]


@router.get("/{invoice_id}/file")
async def download_file(
    request: Request, invoice_id: uuid.UUID, principal: Principal = Depends(require_user)
) -> Response:
    """Descarga autenticada: primero la fila bajo RLS, luego el fichero (S2.7)."""
    tenant = _tenant(request)
    company_scoped = principal.role == "user"
    async with tenant_session(tenant.id) as s0:
        cid = await _user_company_id(s0, principal, None) if company_scoped else None
    async with tenant_session(tenant.id, cid, company_scoped=company_scoped) as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        ).scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Factura no encontrada")
        key, mime = invoice.file_key, invoice.file_mime
    storage = build_storage(get_settings())
    content = await storage.load(key)
    return Response(content=content, media_type=mime)
