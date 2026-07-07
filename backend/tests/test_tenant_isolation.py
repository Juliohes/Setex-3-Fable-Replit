"""Suite anti-cruce de tenants (gate de CI, §8 del plan).

Cierra TST-7: ya NO es `assert True`. Ejecuta contra un PostgreSQL real
(variable TEST_DATABASE_URL) y verifica:
  1. Sin `app.tenant_id` ⇒ 0 filas (RLS fail-closed, ARQ-4).
  2. El tenant A no ve filas del tenant B.
  3. Aislamiento bajo CONCURRENCIA (asyncio.gather) — el escenario exacto de
     la fuga de contexto con pooling que describía ARQ-1.
Si no hay BD disponible, se marca `skip` con razón (nunca un verde falso).
"""
import asyncio
import os
import uuid

import pytest

pytestmark = pytest.mark.isolation

TEST_DB = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL no definida: gate requiere PostgreSQL real")
@pytest.mark.asyncio
async def test_rls_aislamiento_concurrente():
    os.environ["DATABASE_URL"] = TEST_DB
    from sqlalchemy import select, text

    from companies.models import Company
    from shared.bootstrap import init_db
    from shared.db import SessionLocal, engine, tenant_session
    from tenancy.models import Tenant

    await init_db(engine)

    t_a, t_b = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as s:
        async with s.begin():
            s.add(Tenant(id=t_a, slug=f"a{t_a.hex[:8]}", name="Tenant A"))
            s.add(Tenant(id=t_b, slug=f"b{t_b.hex[:8]}", name="Tenant B"))
    async with tenant_session(t_a) as s:
        s.add(Company(tenant_id=t_a, name="Empresa A", cif="A58818501"))
    async with tenant_session(t_b) as s:
        s.add(Company(tenant_id=t_b, name="Empresa B", cif="B65410011"))

    # 1) Fail-closed: sin contexto ⇒ 0 filas
    async with SessionLocal() as s:
        rows = (await s.execute(select(Company))).scalars().all()
        assert rows == []

    # 2+3) Concurrencia: N lecturas simultáneas de A y B jamás se cruzan
    async def read(tenant_id, expected_cif):
        async with tenant_session(tenant_id) as s:
            got = (await s.execute(select(Company.cif))).scalars().all()
            assert got == [expected_cif], f"CRUCE DE TENANTS: {got}"

    await asyncio.gather(*[
        read(t_a, "A58818501") if i % 2 == 0 else read(t_b, "B65410011") for i in range(40)
    ])

    # 4) Escritura cruzada: INSERT con tenant ajeno viola WITH CHECK
    from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

    with pytest.raises((DBAPIError, IntegrityError, ProgrammingError)):
        async with tenant_session(t_a) as s:
            s.add(Company(tenant_id=t_b, name="Intrusa", cif="A08663619"))
            await s.flush()

    # Limpieza: el DELETE debe hacerse DENTRO del contexto de cada tenant —
    # sin contexto, el propio RLS lo bloquea (otra prueba del fail-closed).
    for tid in (t_a, t_b):
        async with tenant_session(tid) as s:
            await s.execute(text("DELETE FROM companies"))
    async with SessionLocal() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM tenants WHERE id IN (:a,:b)"), {"a": t_a, "b": t_b})
