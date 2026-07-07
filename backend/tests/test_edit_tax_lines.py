"""Edición del desglose de IVA desde el panel del admin (PATCH /invoices/{id}/tax-lines).

Ejecuta contra un PostgreSQL real (TEST_DATABASE_URL). Verifica el contrato del
endpoint llamando a la función del router directamente (sin capa HTTP): un desglose
que CUADRA reemplaza los tramos y devuelve el ReviewOut actualizado; un desglose con
un tipo de IVA no permitido (7%) o que descuadra se rechaza con DomainError 4xx.
"""
import os
import types
import uuid
from decimal import Decimal

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DB, reason="TEST_DATABASE_URL no definida: requiere PostgreSQL real"
)


def _fake_request(tenant):
    """Request mínimo: el router solo lee request.state.tenant."""
    return types.SimpleNamespace(state=types.SimpleNamespace(tenant=tenant))


async def _seed(tenant_id, company_id, invoice_id):
    from companies.models import Company
    from invoice_intake.models import Invoice, InvoiceTaxLine
    from shared.db import SessionLocal, tenant_session
    from tenancy.models import Tenant

    async with SessionLocal() as s:
        async with s.begin():
            s.add(Tenant(id=tenant_id, slug=f"t{tenant_id.hex[:8]}", name="Asesoría Test"))
    async with tenant_session(tenant_id) as s:
        s.add(Company(id=company_id, tenant_id=tenant_id, name="Empresa Test", cif="B65410011"))
    async with tenant_session(tenant_id) as s:
        s.add(
            Invoice(
                id=invoice_id, tenant_id=tenant_id, company_id=company_id,
                uploaded_by=uuid.uuid4(), type="received", status="pending_review",
                total=Decimal("121.00"), file_key="k", file_mime="application/pdf",
                file_hash_sha256=uuid.uuid4().hex,
            )
        )
        s.add(
            InvoiceTaxLine(
                tenant_id=tenant_id, company_id=company_id, invoice_id=invoice_id,
                iva_pct=Decimal("21"), base=Decimal("100.00"), cuota=Decimal("21.00"),
            )
        )


async def _cleanup(tenant_id):
    from sqlalchemy import text

    from shared.db import SessionLocal, tenant_session

    async with tenant_session(tenant_id) as s:
        await s.execute(text("DELETE FROM ocr_corrections"))
        await s.execute(text("DELETE FROM invoice_tax_lines"))
        await s.execute(text("DELETE FROM invoices"))
        await s.execute(text("DELETE FROM companies"))
    async with SessionLocal() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM audit_log WHERE tenant_id = :t"), {"t": tenant_id})
            await s.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


async def test_edit_tax_lines_cuadra_y_rechaza():
    os.environ["DATABASE_URL"] = TEST_DB
    from sqlalchemy import select

    from invoice_intake.models import InvoiceTaxLine
    from invoice_intake.router import TaxLineIn, TaxLinesEditIn, edit_tax_lines
    from security.rbac import Principal
    from shared.bootstrap import init_db
    from shared.db import engine, tenant_session
    from shared.exceptions import DomainError

    await init_db(engine)

    tenant_id, company_id, invoice_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tenant = types.SimpleNamespace(id=tenant_id, slug=f"t{tenant_id.hex[:8]}")
    admin = Principal(
        subject_type="user", subject_id=uuid.uuid4(), tenant_id=tenant_id, role="tenant_admin"
    )
    request = _fake_request(tenant)

    try:
        await _seed(tenant_id, company_id, invoice_id)

        # 1) Desglose que CUADRA (2 tramos, 21% + 10%): 105 base + 16 cuota = 121 total.
        ok_body = TaxLinesEditIn(tax_lines=[
            TaxLineIn(iva_pct=Decimal("21"), base=Decimal("50.00"), cuota=Decimal("10.50")),
            TaxLineIn(iva_pct=Decimal("10"), base=Decimal("55.00"), cuota=Decimal("5.50")),
        ])
        out = await edit_tax_lines(request, invoice_id, ok_body, admin)
        assert len(out.tax_lines) == 2
        assert out.total == Decimal("121.00")
        pcts = sorted(tl.iva_pct for tl in out.tax_lines)
        assert pcts == [Decimal("10"), Decimal("21")]

        # Persistencia real: los tramos se reemplazaron en la BD.
        async with tenant_session(tenant_id) as s:
            lines = (await s.execute(
                select(InvoiceTaxLine).where(InvoiceTaxLine.invoice_id == invoice_id)
            )).scalars().all()
        assert len(lines) == 2

        # 2) Tipo de IVA no permitido (7%) → rechazo 4xx.
        bad_pct = TaxLinesEditIn(tax_lines=[
            TaxLineIn(iva_pct=Decimal("7"), base=Decimal("100.00"), cuota=Decimal("7.00")),
        ])
        with pytest.raises(DomainError) as exc:
            await edit_tax_lines(request, invoice_id, bad_pct, admin)
        assert "Tipo de IVA no permitido" in str(exc.value)

        # 3) Tipos válidos pero desglose que DESCUADRA contra el total → rechazo 4xx.
        descuadra = TaxLinesEditIn(tax_lines=[
            TaxLineIn(iva_pct=Decimal("21"), base=Decimal("10.00"), cuota=Decimal("2.10")),
        ])
        with pytest.raises(DomainError) as exc2:
            await edit_tax_lines(request, invoice_id, descuadra, admin)
        assert "no cuadra" in str(exc2.value).lower()

        # Tras los rechazos, el desglose válido (2 tramos) sigue intacto.
        async with tenant_session(tenant_id) as s:
            lines = (await s.execute(
                select(InvoiceTaxLine).where(InvoiceTaxLine.invoice_id == invoice_id)
            )).scalars().all()
        assert len(lines) == 2
    finally:
        await _cleanup(tenant_id)
        # El engine global mantiene un pool ligado a ESTE event loop; sin liberarlo,
        # el siguiente test async reutilizaría conexiones de un loop ya cerrado.
        await engine.dispose()
