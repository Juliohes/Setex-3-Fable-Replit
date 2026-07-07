"""Seed inicial: admins de plataforma + tenant Setex + tenant demo 'tuti'.

Uso (Replit Shell o local):
    python scripts/seed.py
Idempotente: si ya existe, no duplica. Las contraseñas iniciales se imprimen
UNA vez por consola; cambiarlas en el primer login.
"""
from __future__ import annotations

import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from sqlalchemy import select  # noqa: E402

from identity.models import PlatformAdmin, User  # noqa: E402
from security.auth import hash_password  # noqa: E402
from shared.bootstrap import init_db  # noqa: E402
from shared.config import get_settings  # noqa: E402
from shared.db import engine, plain_session, tenant_session  # noqa: E402
from tenancy.models import Tenant, TenantBranding  # noqa: E402


async def main() -> None:
    settings = get_settings()
    await init_db(engine)
    printed: list[str] = []

    async with plain_session() as session:
        emails = [e.strip().lower() for e in settings.platform_admin_emails.split(",") if e.strip()]
        for email in emails:
            exists = await session.execute(select(PlatformAdmin.id).where(PlatformAdmin.email == email))
            if exists.scalar_one_or_none() is None:
                pwd = secrets.token_urlsafe(14)
                session.add(PlatformAdmin(email=email, password_hash=hash_password(pwd)))
                printed.append(f"platform_admin {email} → contraseña inicial: {pwd}")

        tenants = {
            "setex": ("Setex Asesores", "#FF7A00", "#1C1C1E", False),
            "tuti": ("Asesoría Demo Tuti", "#0E7C7B", "#101418", True),
        }
        tenant_ids: dict[str, object] = {}
        for slug, (name, c1, c2, demo) in tenants.items():
            row = await session.execute(select(Tenant).where(Tenant.slug == slug))
            tenant = row.scalar_one_or_none()
            if tenant is None:
                tenant = Tenant(slug=slug, name=name, is_demo=demo)
                session.add(tenant)
                await session.flush()
                session.add(TenantBranding(tenant_id=tenant.id, app_name=name,
                                           color_primary=c1, color_secondary=c2))
            tenant_ids[slug] = tenant.id

    for slug, admin_email in (("setex", "admin-setex@autoken.es"), ("tuti", "admin-tuti@autoken.es")):
        async with tenant_session(tenant_ids[slug]) as session:
            exists = await session.execute(select(User.id).where(User.email == admin_email))
            if exists.scalar_one_or_none() is None:
                pwd = secrets.token_urlsafe(14)
                session.add(User(tenant_id=tenant_ids[slug], email=admin_email,
                                 full_name="Administración", password_hash=hash_password(pwd),
                                 role="tenant_admin", status="active"))
                printed.append(f"tenant_admin {slug} ({admin_email}) → contraseña inicial: {pwd}")

    await engine.dispose()
    print("Seed completado.")
    for line in printed:
        print("  ·", line)


if __name__ == "__main__":
    asyncio.run(main())
