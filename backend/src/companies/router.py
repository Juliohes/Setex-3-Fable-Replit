"""Empresas: CRUD, aprobación e import del Excel (S1.5)."""
from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, Depends, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from companies.models import Company
from invoice_intake.models import Invoice
from ocr.verification import validate_tax_id
from security.audit import write_audit
from security.rbac import Principal, require_tenant_admin
from shared.db import plain_session, tenant_session
from shared.exceptions import ConflictError, DomainError, NotFoundError

router = APIRouter(prefix="/companies", tags=["companies"])


def _tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise NotFoundError("Asesoría no encontrada")
    return tenant


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    cif: str
    notes: str = ""


class CompanyOut(BaseModel):
    id: str
    name: str
    cif: str
    status: str
    notes: str
    invoice_count: int = 0


@router.get("", response_model=list[CompanyOut])
async def list_companies(
    request: Request, admin: Principal = Depends(require_tenant_admin)
) -> list[CompanyOut]:
    tenant = _tenant(request)
    async with tenant_session(tenant.id) as session:
        rows = (await session.execute(select(Company).order_by(Company.name))).scalars().all()
        counts = dict(
            (await session.execute(
                select(Invoice.company_id, func.count()).group_by(Invoice.company_id)
            )).all()
        )
    return [
        CompanyOut(id=str(c.id), name=c.name, cif=c.cif, status=c.status, notes=c.notes,
                   invoice_count=counts.get(c.id, 0))
        for c in rows
    ]


@router.post("", response_model=CompanyOut, status_code=201)
async def create_company(
    request: Request, body: CompanyIn, admin: Principal = Depends(require_tenant_admin)
) -> CompanyOut:
    tenant = _tenant(request)
    check = validate_tax_id(body.cif)
    if not check.valid:
        raise DomainError(f"CIF inválido: {check.reason}")
    clean = "".join(body.cif.split()).upper()
    async with tenant_session(tenant.id) as session:
        dup = await session.execute(select(Company.id).where(Company.cif == clean))
        if dup.scalar_one_or_none() is not None:
            raise ConflictError("Ya existe una empresa con ese CIF")
        company = Company(tenant_id=tenant.id, name=body.name, cif=clean, notes=body.notes)
        session.add(company)
        await session.flush()
        out = CompanyOut(id=str(company.id), name=company.name, cif=company.cif,
                         status=company.status, notes=company.notes)
    async with plain_session() as session:
        await write_audit(session, tenant_id=tenant.id, actor_type="tenant_admin",
                          actor_id=admin.subject_id, action="company_created",
                          entity="company", entity_id=out.id, payload={"cif": clean})
    return out


@router.post("/{company_id}/approve")
async def approve_company(
    request: Request, company_id: uuid.UUID, admin: Principal = Depends(require_tenant_admin)
) -> dict:
    tenant = _tenant(request)
    async with tenant_session(tenant.id) as session:
        company = (
            await session.execute(select(Company).where(Company.id == company_id))
        ).scalar_one_or_none()
        if company is None:
            raise NotFoundError("Empresa no encontrada")
        company.status = "active"
    return {"detail": "Empresa activada"}


class ImportReport(BaseModel):
    created: int
    skipped_duplicates: int
    errors: list[str]


@router.post("/import-excel", response_model=ImportReport)
async def import_excel(
    request: Request, file: UploadFile, admin: Principal = Depends(require_tenant_admin)
) -> ImportReport:
    """Importador del Excel de la asesoría (columnas: nombre, CIF [, notas])."""
    tenant = _tenant(request)
    try:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(await file.read()), read_only=True, data_only=True)
        ws = wb.active
    except Exception as exc:
        raise DomainError(f"No se pudo leer el Excel: {exc}") from exc
    created, skipped, errors = 0, 0, []
    async with tenant_session(tenant.id) as session:
        existing = {c for (c,) in (await session.execute(select(Company.cif))).all()}
        for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if row is None or all(v is None for v in row):
                continue
            name = str(row[0] or "").strip()
            cif = "".join(str(row[1] or "").split()).upper()
            notes = str(row[2] or "").strip() if len(row) > 2 else ""
            if not name or not cif:
                errors.append(f"Fila {idx}: falta nombre o CIF")
                continue
            check = validate_tax_id(cif)
            if not check.valid:
                errors.append(f"Fila {idx} ({name}): {check.reason}")
                continue
            if cif in existing:
                skipped += 1
                continue
            session.add(Company(tenant_id=tenant.id, name=name, cif=cif, notes=notes))
            existing.add(cif)
            created += 1
    async with plain_session() as session:
        await write_audit(session, tenant_id=tenant.id, actor_type="tenant_admin",
                          actor_id=admin.subject_id, action="companies_imported",
                          entity="company", payload={"created": created, "errors": len(errors)})
    return ImportReport(created=created, skipped_duplicates=skipped, errors=errors)
