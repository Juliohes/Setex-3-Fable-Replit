"""Healthcheck (BP-3 cerrado: settings por Depends, testeable con overrides)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from shared.config import Settings, get_settings

router = APIRouter(tags=["platform"])


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env.value,
    }
