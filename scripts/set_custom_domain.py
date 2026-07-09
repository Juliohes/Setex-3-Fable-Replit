"""Asigna (o quita) el dominio propio de una asesoría.

Cuando el subdominio no coincide con el slug interno (p. ej. slug 'setex' pero
dominio 'setex-fable.autoken.es'), la app resuelve la asesoría por su
`custom_domain`. Este script lo configura.

Uso:
    python scripts/set_custom_domain.py --tenant setex --domain setex-fable.autoken.es
    python scripts/set_custom_domain.py --tenant setex --clear      # quitar el dominio
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from sqlalchemy import select  # noqa: E402

from shared.bootstrap import init_db  # noqa: E402
from shared.db import engine, plain_session  # noqa: E402
from tenancy.models import Tenant  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="Asigna el dominio propio de una asesoría.")
    ap.add_argument("--tenant", required=True, help="Slug de la asesoría")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--domain", help="Dominio propio (p. ej. setex-fable.autoken.es)")
    group.add_argument("--clear", action="store_true", help="Quita el dominio propio")
    args = ap.parse_args()

    domain = None if args.clear else args.domain.strip().lower().split("/")[0]
    await init_db(engine)

    async with plain_session() as s:
        tenant = (
            await s.execute(select(Tenant).where(Tenant.slug == args.tenant))
        ).scalar_one_or_none()
        if tenant is None:
            print(f"ERROR: no existe la asesoría con slug '{args.tenant}'")
            await engine.dispose()
            return 2
        if domain is not None:
            clash = (
                await s.execute(
                    select(Tenant.slug).where(
                        Tenant.custom_domain == domain, Tenant.slug != args.tenant
                    )
                )
            ).scalar_one_or_none()
            if clash is not None:
                print(f"ERROR: el dominio '{domain}' ya está asignado a la asesoría '{clash}'")
                await engine.dispose()
                return 2
        tenant.custom_domain = domain

    await engine.dispose()
    if domain is None:
        print(f"OK: dominio propio eliminado de la asesoría '{args.tenant}'.")
    else:
        print(f"OK: la asesoría '{args.tenant}' ahora responde también en '{domain}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
