"""Almacenamiento de ficheros (ADR-0012: sustituye a MinIO en modo Replit).

Puerto + adapters: local (desarrollo) y Replit App Storage (producción).
Aislamiento por PREFIJO de tenant en la clave; la descarga SIEMPRE pasa por
un endpoint autenticado que primero recupera la factura bajo RLS — no hay
URLs públicas que adivinar (cubre S2.7 sin URLs firmadas).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol

from shared.config import Settings


class Storage(Protocol):
    async def save(self, key: str, content: bytes, mime: str) -> None: ...

    async def load(self, key: str) -> bytes: ...


class LocalStorage:
    def __init__(self, base_dir: str) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self._base / key).resolve()
        if not str(p).startswith(str(self._base.resolve())):
            raise ValueError("clave de fichero inválida")  # anti path-traversal
        return p

    async def save(self, key: str, content: bytes, mime: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)

    async def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class ReplitObjectStorage:
    """Adapter del App Storage de Replit (paquete `replit-object-storage`)."""

    def __init__(self) -> None:
        from replit.object_storage import Client  # import diferido: solo existe en Replit

        self._client = Client()

    async def save(self, key: str, content: bytes, mime: str) -> None:
        self._client.upload_from_bytes(key, content)

    async def load(self, key: str) -> bytes:
        return self._client.download_as_bytes(key)


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "replit":
        return ReplitObjectStorage()
    return LocalStorage(settings.storage_local_dir)


def make_file_key(tenant_id: uuid.UUID, invoice_id: uuid.UUID, mime: str) -> str:
    ext = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}.get(mime, "bin")
    return f"invoices/{tenant_id}/{invoice_id}.{ext}"
