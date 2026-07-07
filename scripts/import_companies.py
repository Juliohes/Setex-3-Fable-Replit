"""Importador CLI del Excel de empresas de una asesoría (Fase 8).

Espejo exacto de la lógica del endpoint POST /companies/import-excel:
columnas fila 1 = cabecera; A = nombre, B = CIF/NIF/NIE, C = notas (opcional).
Valida cada identificador fiscal con su dígito de control y salta duplicados
(por la restricción única tenant+cif, respetando RLS via tenant_session).

Uso:
    # Vista previa (NO escribe nada): valida y muestra el informe fila a fila
    python scripts/import_companies.py <ruta_excel.xlsx> --tenant setex

    # Importación real (escribe en la BD del tenant):
    python scripts/import_companies.py <ruta_excel.xlsx> --tenant setex --commit

Por seguridad, el modo por defecto es DRY-RUN: revisa el informe y solo cuando
esté limpio repite con --commit. Idempotente: reejecutar salta los ya existentes.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from sqlalchemy import select  # noqa: E402

from companies.models import Company  # noqa: E402
from ocr.verification import validate_tax_id  # noqa: E402
from shared.bootstrap import init_db  # noqa: E402
from shared.db import engine, plain_session, tenant_session  # noqa: E402
from tenancy.models import Tenant  # noqa: E402


def _read_rows(path: Path) -> list[tuple[str, str, str]]:
    """Lee el Excel igual que el endpoint: cabecera en fila 1, datos desde la 2."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows: list[tuple[str, str, str]] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row is None or all(v is None for v in row):
            continue
        name = str(row[0] or "").strip() if len(row) > 0 else ""
        cif = "".join(str(row[1] or "").split()).upper() if len(row) > 1 else ""
        notes = str(row[2] or "").strip() if len(row) > 2 else ""
        rows.append((name, cif, notes))
    wb.close()
    return rows


async def main() -> int:
    ap = argparse.ArgumentParser(description="Importa el Excel de empresas de una asesoría.")
    ap.add_argument("excel", help="Ruta al fichero .xlsx")
    ap.add_argument("--tenant", default="setex", help="Slug de la asesoría (por defecto: setex)")
    ap.add_argument("--commit", action="store_true", help="Escribe en la BD (sin él es dry-run)")
    args = ap.parse_args()

    path = Path(args.excel)
    if not path.exists():
        print(f"ERROR: no existe el fichero {path}")
        return 2

    try:
        rows = _read_rows(path)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: no se pudo leer el Excel: {exc}")
        return 2

    await init_db(engine)

    async with plain_session() as session:
        res = await session.execute(select(Tenant).where(Tenant.slug == args.tenant))
        tenant = res.scalar_one_or_none()
    if tenant is None:
        print(f"ERROR: no existe la asesoría con slug '{args.tenant}'.")
        await engine.dispose()
        return 2

    created, skipped, errors, to_insert = 0, 0, [], []
    async with tenant_session(tenant.id) as session:
        existing = {c for (c,) in (await session.execute(select(Company.cif))).all()}
        for idx, (name, cif, notes) in enumerate(rows, start=2):
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
            existing.add(cif)
            created += 1
            to_insert.append((name, cif, notes))
            if args.commit:
                session.add(Company(tenant_id=tenant.id, name=name, cif=cif, notes=notes))
        if not args.commit:
            # tenant_session hace commit al salir; en dry-run descartamos los cambios.
            await session.rollback()

    await engine.dispose()

    modo = "IMPORTACIÓN REAL" if args.commit else "VISTA PREVIA (dry-run, no se ha escrito nada)"
    print(f"\n=== {modo} — asesoría '{args.tenant}' ({len(rows)} filas con datos) ===")
    print(f"  Nuevas a crear : {created}")
    print(f"  Duplicadas     : {skipped}")
    print(f"  Errores        : {len(errors)}")
    if errors:
        print("\n  Detalle de errores:")
        for e in errors:
            print("   ·", e)
    if not args.commit and created:
        print(f"\n  → Informe limpio? Repite con --commit para crear las {created} empresas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
