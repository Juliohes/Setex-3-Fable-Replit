"""Adapter VIES (Comisión Europea) vía API REST oficial.

Cobertura limitada al ROI (§11.8.2): un "no encontrado" en VIES NO bloquea por
sí solo — muchos proveedores nacionales legítimos no están dados de alta.
"""
from __future__ import annotations

import httpx

from ocr.counterparty.resolvers.base import Resolution

_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"


class ViesResolver:
    source = "vies"

    async def resolve(self, cif: str) -> Resolution:
        clean = cif.upper().replace(" ", "").removeprefix("ES")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(_URL, json={"countryCode": "ES", "vatNumber": clean})
            resp.raise_for_status()
            data = resp.json()
        if data.get("valid") is True:
            name = (data.get("name") or "").strip()
            return Resolution(resolved=True, exists=True, official_name=name or None, raw=data)
        return Resolution(resolved=True, exists=False, raw=data)
