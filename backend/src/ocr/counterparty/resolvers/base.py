"""Puerto CifResolver + decorador de timeout (Nygard: estabilidad en el borde).

ARQ-6: la caída o lentitud de un tercero NUNCA bloquea; devuelve 'unresolved'
y la UI muestra "Revisar manual". El timeout vive AQUÍ (una vez), no en cada
adapter (PAT-5: decorador del puerto).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Resolution:
    resolved: bool            # ¿la fuente respondió con veredicto?
    exists: bool = False
    official_name: str | None = None
    raw: dict | None = None


class CifResolver(Protocol):
    source: str

    async def resolve(self, cif: str) -> Resolution: ...


class TimeoutResolver:
    """Decorador: aplica timeout y convierte cualquier fallo en 'unresolved'."""

    def __init__(self, inner: CifResolver, timeout_seconds: float) -> None:
        self._inner = inner
        self._timeout = timeout_seconds
        self.source = inner.source

    async def resolve(self, cif: str) -> Resolution:
        try:
            return await asyncio.wait_for(self._inner.resolve(cif), timeout=self._timeout)
        except Exception:
            return Resolution(resolved=False)
