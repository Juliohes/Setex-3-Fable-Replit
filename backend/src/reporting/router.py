"""Panel de asesoría: consultas de solo lectura + export Excel (PAT-9, CQRS-light)."""
from __future__ import annotations

import datetime as dt
import io
import re
import unicodedata
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from companies.models import Company
from invoice_intake.models import Invoice, InvoiceIrpf, InvoiceTaxLine
from security.rbac import Principal, require_tenant_admin
from shared.db import tenant_session
from shared.exceptions import NotFoundError

router = APIRouter(prefix="/reporting", tags=["reporting"])

# Cabeceras EXACTAS del export de producción (respeta acentos, º y €). No tocar.
FACTURAS_HEADER = [
    "ID", "Empresa", "CIF Empresa", "Cliente / Proveedor", "CIF Cl/Prov", "Nº Factura",
    "Fecha", "Base Imponible", "Total (€)", "IVA %", "Cuota IVA", "IRPF %", "Cuota IRPF", "Moneda",
]
DESGLOSE_HEADER = [
    "ID", "Empresa", "CIF Empresa", "Cliente / Proveedor", "CIF Cl/Prov", "Nº Factura",
    "Fecha", "IVA %", "Base tramo (€)", "Cuota tramo (€)", "Total tramo (€)", "Productos del tramo",
]


def _money(value: Any) -> float:
    """Importe monetario con 2 decimales correctos (NO truncado; ver informe)."""
    if value is None:
        return 0.0
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _pct(value: Any) -> float | int:
    """Porcentaje: entero si es entero (10.00→10), si no float (p.ej. 4.5)."""
    if value is None:
        return 0
    d = Decimal(str(value))
    return int(d) if d == d.to_integral_value() else float(d)


def _fecha(value: dt.date | None) -> str:
    """Fecha en formato dd/mm/yyyy (formato de la referencia de producción)."""
    return value.strftime("%d/%m/%Y") if value else ""


def _slugify(name: str) -> str:
    """'RUTA DEL CORCHO' -> 'ruta-del-corcho' (minúsculas, sin acentos, espacios→guiones)."""
    norm = unicodedata.normalize("NFKD", name or "")
    ascii_str = norm.encode("ascii", "ignore").decode("ascii").lower()
    ascii_str = re.sub(r"[^a-z0-9]+", "-", ascii_str)
    return ascii_str.strip("-")


def export_filename(
    tenant_slug: str,
    date_from: dt.date | None,
    date_to: dt.date | None,
    company_name: str | None = None,
) -> str:
    """<slug_tenant>_facturas_<desde>_<hasta>[_<slug_empresa>].xlsx (refleja los filtros)."""
    desde = date_from.isoformat() if date_from else "todas"
    hasta = date_to.isoformat() if date_to else "todas"
    parts = [_slugify(tenant_slug) or "asesoria", "facturas", desde, hasta]
    if company_name:
        empresa_slug = _slugify(company_name)
        if empresa_slug:
            parts.append(empresa_slug)
    return "_".join(parts) + ".xlsx"


def build_workbook(rows_data: list[dict[str, Any]]):
    """Construye el Workbook (2 hojas) a partir de datos puros; testeable sin BD.

    Cada elemento de rows_data: empresa, cif_empresa, contraparte, cif_contraparte,
    num_factura, fecha (date|None), total, irpf_pct, irpf_cuota,
    tramos=[{iva_pct, base, cuota}, ...].
    """
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Facturas"
    ws.append(FACTURAS_HEADER)

    ws2 = wb.create_sheet("Desglose IVA")
    ws2.append(DESGLOSE_HEADER)

    for r in rows_data:
        tramos = r.get("tramos") or []
        base_total = sum((Decimal(str(t["base"])) for t in tramos), Decimal("0"))
        cuota_total = sum((Decimal(str(t["cuota"])) for t in tramos), Decimal("0"))
        # IVA %: si hay exactamente 1 tramo, su porcentaje; si hay varios, "N tramos".
        # El detalle por tramo vive en la hoja "Desglose IVA" (no se toca).
        if len(tramos) == 1:
            iva_repr: float | int | str = _pct(tramos[0]["iva_pct"])
        elif tramos:
            iva_repr = f"{len(tramos)} tramos"
        else:
            iva_repr = 0

        fecha = _fecha(r.get("fecha"))
        ws.append([
            "",  # ID: vacío en la referencia
            r.get("empresa", ""),
            r.get("cif_empresa", ""),
            r.get("contraparte", "") or "",
            r.get("cif_contraparte", "") or "",
            r.get("num_factura", "") or "",
            fecha,
            _money(base_total),
            _money(r.get("total")),
            iva_repr,
            _money(cuota_total),
            _pct(r.get("irpf_pct")),
            _money(r.get("irpf_cuota")),
            "EUR",
        ])

        for t in tramos:
            base = Decimal(str(t["base"]))
            cuota = Decimal(str(t["cuota"]))
            ws2.append([
                "",
                r.get("empresa", ""),
                r.get("cif_empresa", ""),
                r.get("contraparte", "") or "",
                r.get("cif_contraparte", "") or "",
                r.get("num_factura", "") or "",
                fecha,
                _pct(t["iva_pct"]),
                _money(base),
                _money(cuota),
                _money(base + cuota),
                "",  # Productos del tramo: el modelo no los guarda (vacío en la referencia)
            ])
    return wb


def _tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise NotFoundError("Asesoría no encontrada")
    return tenant


class PanelRow(BaseModel):
    id: str
    company: str
    type: str
    status: str
    invoice_number: str | None
    issue_date: dt.date | None
    counterparty: str | None
    counterparty_cif: str | None
    total: Decimal | None
    tax_line_count: int
    created_at: dt.datetime


def _filters(stmt, date_from, date_to, status, cif):
    if date_from:
        stmt = stmt.where(Invoice.issue_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.issue_date <= date_to)
    if status:
        stmt = stmt.where(Invoice.status == status)
    if cif:
        clean = "".join(cif.split()).upper()
        stmt = stmt.where((Invoice.supplier_cif == clean) | (Invoice.receiver_cif == clean))
    return stmt.where(Invoice.is_test.is_(False))  # regla 3: pruebas fuera de informes


@router.get("/invoices", response_model=list[PanelRow])
async def panel_invoices(
    request: Request,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    status: str | None = None,
    cif: str | None = None,
    limit: int = 200,
    admin: Principal = Depends(require_tenant_admin),
) -> list[PanelRow]:
    tenant = _tenant(request)
    async with tenant_session(tenant.id) as session:
        stmt = _filters(select(Invoice), date_from, date_to, status, cif)
        rows = (
            await session.execute(stmt.order_by(Invoice.created_at.desc()).limit(min(limit, 500)))
        ).scalars().all()
        companies = dict((await session.execute(select(Company.id, Company.name))).all())
        # Una sola query agrupada para el nº de tramos de las facturas devueltas (no N+1).
        invoice_ids = [i.id for i in rows]
        counts: dict[uuid.UUID, int] = {}
        if invoice_ids:
            counts = dict(
                (await session.execute(
                    select(InvoiceTaxLine.invoice_id, func.count())
                    .where(InvoiceTaxLine.invoice_id.in_(invoice_ids))
                    .group_by(InvoiceTaxLine.invoice_id)
                )).all()
            )
    return [
        PanelRow(
            id=str(i.id),
            company=companies.get(i.company_id, ""),
            type=i.type, status=i.status,
            invoice_number=i.invoice_number, issue_date=i.issue_date,
            counterparty=i.supplier_name if i.type == "received" else i.receiver_name,
            counterparty_cif=i.supplier_cif if i.type == "received" else i.receiver_cif,
            total=i.total, tax_line_count=counts.get(i.id, 0), created_at=i.created_at,
        )
        for i in rows
    ]


@router.get("/invoices.xlsx")
async def export_excel(
    request: Request,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    status: str | None = None,
    cif: str | None = None,
    admin: Principal = Depends(require_tenant_admin),
) -> Response:
    """Export Excel con los filtros aplicados (S3.2). Formato idéntico al de producción."""
    tenant = _tenant(request)
    rows_data: list[dict[str, Any]] = []
    company_name_for_filename: str | None = None
    async with tenant_session(tenant.id) as session:
        stmt = _filters(select(Invoice), date_from, date_to, status, cif)
        invoices = (await session.execute(stmt.order_by(Invoice.issue_date))).scalars().all()
        companies = dict(
            (cid, (name, cif_val))
            for cid, name, cif_val in (
                await session.execute(select(Company.id, Company.name, Company.cif))
            ).all()
        )
        if cif:
            clean = "".join(cif.split()).upper()
            match = (
                await session.execute(select(Company.name).where(Company.cif == clean))
            ).scalar_one_or_none()
            company_name_for_filename = match
        for i in invoices:
            lines = (
                await session.execute(
                    select(InvoiceTaxLine).where(InvoiceTaxLine.invoice_id == i.id)
                )
            ).scalars().all()
            irpf = (
                await session.execute(select(InvoiceIrpf).where(InvoiceIrpf.invoice_id == i.id))
            ).scalar_one_or_none()
            empresa_name, empresa_cif = companies.get(i.company_id, ("", ""))
            rows_data.append({
                "empresa": empresa_name,
                "cif_empresa": empresa_cif,
                "contraparte": i.supplier_name if i.type == "received" else i.receiver_name,
                "cif_contraparte": i.supplier_cif if i.type == "received" else i.receiver_cif,
                "num_factura": i.invoice_number,
                "fecha": i.issue_date,
                "total": i.total,
                "irpf_pct": irpf.pct if irpf else 0,
                "irpf_cuota": irpf.cuota if irpf else 0,
                "tramos": [
                    {"iva_pct": ln.iva_pct, "base": ln.base, "cuota": ln.cuota} for ln in lines
                ],
            })

    wb = build_workbook(rows_data)
    buf = io.BytesIO()
    wb.save(buf)
    fname = export_filename(tenant.slug, date_from, date_to, company_name_for_filename)
    disposition = f"attachment; filename=\"{fname}\"; filename*=UTF-8''{quote(fname)}"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )
