"""Branding público por tenant (theming runtime, S4.2)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from shared.db import plain_session
from shared.exceptions import NotFoundError
from tenancy.models import TenantBranding

router = APIRouter(tags=["tenancy"])


class BrandingOut(BaseModel):
    tenant_slug: str
    app_name: str
    logo_url: str | None
    color_primary: str
    color_secondary: str


@router.get("/branding", response_model=BrandingOut)
async def get_branding(request: Request) -> BrandingOut:
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise NotFoundError("Asesoría no encontrada")  # 404 neutro (S1.2)
    async with plain_session() as session:
        row = await session.execute(select(TenantBranding).where(TenantBranding.tenant_id == tenant.id))
        b = row.scalar_one_or_none()
    return BrandingOut(
        tenant_slug=tenant.slug,
        app_name=b.app_name if b else tenant.name,
        logo_url=b.logo_url if b else None,
        color_primary=b.color_primary if b else "#FF7A00",
        color_secondary=b.color_secondary if b else "#1C1C1E",
    )
