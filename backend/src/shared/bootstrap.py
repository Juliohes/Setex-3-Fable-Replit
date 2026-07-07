"""Arranque de esquema para modo Replit (AUTO_MIGRATE=1).

Crea tablas y aplica RLS de forma idempotente. Alembic queda cableado en
`migrations/` para evolucionar el esquema a partir de aquí (ADR-0012).

BD-12: el RLS vive junto al esquema con un helper único (`_apply_tenant_rls`),
así ninguna tabla de negocio puede quedarse sin política por descuido.
ARQ-4: fail-closed — sin `app.tenant_id` la política evalúa a NULL ⇒ 0 filas.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from shared.db import Base

# Tablas de negocio (RLS FORCE por tenant). Las de plano de plataforma o
# infraestructura (tenants, tenant_branding, platform_admins, refresh_tokens,
# jobs, cif_lookups, audit_log) quedan fuera de forma DELIBERADA y no se
# exponen jamás en endpoints de tenant.
TENANT_TABLES = [
    "users",
    "companies",
    "memberships",
    "invoices",
    "invoice_tax_lines",
    "invoice_irpf",
    "ocr_extractions",
    "ocr_corrections",
    "counterparties",
]

# Tablas con segundo nivel de aislamiento por empresa (política RESTRICTIVA).
COMPANY_TABLES = [
    "invoices",
    "invoice_tax_lines",
    "invoice_irpf",
    "ocr_extractions",
    "ocr_corrections",
]

_TENANT_POLICY = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = '{t}' AND policyname = 'tenant_isolation') THEN
    EXECUTE 'CREATE POLICY tenant_isolation ON {t} '
         || 'USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid) '
         || 'WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)';
  END IF;
END $$;
"""

_COMPANY_POLICY = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = '{t}' AND policyname = 'company_scope') THEN
    EXECUTE 'CREATE POLICY company_scope ON {t} AS RESTRICTIVE '
         || 'USING (NULLIF(current_setting(''app.company_scope'', true), '''') IS NULL '
         || 'OR company_id = NULLIF(current_setting(''app.company_id'', true), '''')::uuid) '
         || 'WITH CHECK (NULLIF(current_setting(''app.company_scope'', true), '''') IS NULL '
         || 'OR company_id = NULLIF(current_setting(''app.company_id'', true), '''')::uuid)';
  END IF;
END $$;
"""


def _register_all_models() -> None:
    """Importa todos los módulos de modelos para poblar Base.metadata.
    Punto único: una tabla nueva se añade AQUÍ o no existe (fail-loud)."""
    import companies.models  # noqa: F401
    import identity.models  # noqa: F401
    import invoice_intake.models  # noqa: F401
    import ocr.models  # noqa: F401
    import security.models  # noqa: F401
    import tenancy.models  # noqa: F401


async def init_db(engine: AsyncEngine) -> None:
    _register_all_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for t in TENANT_TABLES:
            await conn.execute(text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY"))
            await conn.execute(text(_TENANT_POLICY.format(t=t)))
        for t in COMPANY_TABLES:
            await conn.execute(text(_COMPANY_POLICY.format(t=t)))
