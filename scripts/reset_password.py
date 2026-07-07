"""Rota la contraseña de una cuenta (admin de plataforma o admin/usuario de asesoría).

La nueva contraseña se teclea por consola con getpass: NO se muestra en pantalla,
NO se pasa por argumentos y NO queda en el historial de shell ni en logs.

Uso:
    # Admin de asesoría (tenant): indica el slug de la asesoría
    python scripts/reset_password.py --email admin-setex@autoken.es --tenant setex

    # Admin de plataforma
    python scripts/reset_password.py --email juliohesuni@gmail.com --platform

Pide la nueva contraseña dos veces (para confirmar). Mínimo 12 caracteres.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from sqlalchemy import select  # noqa: E402

from identity.models import PlatformAdmin, User  # noqa: E402
from security.auth import hash_password  # noqa: E402
from shared.bootstrap import init_db  # noqa: E402
from shared.db import engine, plain_session, tenant_session  # noqa: E402
from tenancy.models import Tenant  # noqa: E402


def _prompt_password() -> str:
    while True:
        pw1 = getpass.getpass("Nueva contraseña (mín. 12 caracteres): ")
        if len(pw1) < 12:
            print("  Demasiado corta. Prueba de nuevo.")
            continue
        pw2 = getpass.getpass("Repite la contraseña: ")
        if pw1 != pw2:
            print("  No coinciden. Prueba de nuevo.")
            continue
        return pw1


async def main() -> int:
    ap = argparse.ArgumentParser(description="Rota la contraseña de una cuenta.")
    ap.add_argument("--email", required=True, help="Email de la cuenta")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--platform", action="store_true", help="Cuenta de admin de plataforma")
    group.add_argument("--tenant", help="Slug de la asesoría (para admin/usuario de tenant)")
    args = ap.parse_args()

    email = args.email.strip().lower()
    await init_db(engine)

    new_hash_source = _prompt_password()
    new_hash = hash_password(new_hash_source)
    del new_hash_source  # no lo mantengas en memoria más de lo necesario

    if args.platform:
        async with plain_session() as s:
            admin = (await s.execute(
                select(PlatformAdmin).where(PlatformAdmin.email == email)
            )).scalar_one_or_none()
            if admin is None:
                print(f"ERROR: no existe admin de plataforma con email {email}")
                await engine.dispose()
                return 2
            admin.password_hash = new_hash
        print(f"OK: contraseña de plataforma actualizada para {email}.")
    else:
        async with plain_session() as s:
            tenant = (await s.execute(
                select(Tenant).where(Tenant.slug == args.tenant)
            )).scalar_one_or_none()
        if tenant is None:
            print(f"ERROR: no existe la asesoría con slug '{args.tenant}'")
            await engine.dispose()
            return 2
        async with tenant_session(tenant.id) as s:
            user = (await s.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()
            if user is None:
                print(f"ERROR: no existe el usuario {email} en la asesoría '{args.tenant}'")
                await engine.dispose()
                return 2
            user.password_hash = new_hash
        print(f"OK: contraseña actualizada para {email} en la asesoría '{args.tenant}'.")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
